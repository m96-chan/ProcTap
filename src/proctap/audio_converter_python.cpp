/**
 * Python bindings for high-performance audio converter
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "audio_converter_simd.hpp"

using namespace proctap;

/**
 * Convert int16 PCM to float32 PCM
 *
 * Args:
 *     data (bytes): Input int16 PCM data
 *
 * Returns:
 *     bytes: Output float32 PCM data normalized to [-1.0, 1.0]
 */
static PyObject* convert_int16_to_float32(PyObject* self, PyObject* args) {
    Py_buffer buffer;

    // Parse arguments
    if (!PyArg_ParseTuple(args, "y*", &buffer)) {
        return nullptr;
    }

    // Validate input size
    if (buffer.len % 2 != 0) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "Input buffer size must be multiple of 2 (int16 = 2 bytes)");
        return nullptr;
    }

    const size_t sample_count = buffer.len / 2;
    const int16_t* src = static_cast<const int16_t*>(buffer.buf);

    // Allocate output buffer
    PyObject* result = PyBytes_FromStringAndSize(nullptr, sample_count * sizeof(float));
    if (!result) {
        PyBuffer_Release(&buffer);
        return nullptr;
    }

    // Get output buffer pointer
    float* dst = reinterpret_cast<float*>(PyBytes_AS_STRING(result));

    // Perform conversion with SIMD optimization
    Int16ToFloat32Converter::Convert(src, dst, sample_count);

    PyBuffer_Release(&buffer);
    return result;
}

/**
 * Resample audio data
 *
 * Args:
 *     data (bytes): Input float32 PCM data
 *     src_rate (int): Source sample rate
 *     dst_rate (int): Destination sample rate
 *     channels (int): Number of channels
 *     quality (str): "low_latency" or "high_quality"
 *
 * Returns:
 *     bytes: Resampled float32 PCM data
 */
static PyObject* resample_audio(PyObject* self, PyObject* args) {
    Py_buffer buffer;
    int src_rate, dst_rate, channels;
    const char* quality_str;

    // Parse arguments
    if (!PyArg_ParseTuple(args, "y*iiis", &buffer, &src_rate, &dst_rate, &channels, &quality_str)) {
        return nullptr;
    }

    // Validate input
    if (buffer.len % (channels * sizeof(float)) != 0) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "Input buffer size must be multiple of (channels * 4)");
        return nullptr;
    }

    // Determine quality mode
    ResamplingQuality quality;
    if (strcmp(quality_str, "low_latency") == 0) {
        quality = ResamplingQuality::LowLatency;
    } else if (strcmp(quality_str, "high_quality") == 0) {
        quality = ResamplingQuality::HighQuality;
    } else {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "Quality must be 'low_latency' or 'high_quality'");
        return nullptr;
    }

    const size_t src_frames = buffer.len / (channels * sizeof(float));
    const size_t dst_frames = (src_frames * dst_rate) / src_rate;
    const float* src = static_cast<const float*>(buffer.buf);

    // Allocate output buffer
    const size_t dst_size = dst_frames * channels * sizeof(float);
    PyObject* result = PyBytes_FromStringAndSize(nullptr, dst_size);
    if (!result) {
        PyBuffer_Release(&buffer);
        return nullptr;
    }

    // Get output buffer pointer
    float* dst = reinterpret_cast<float*>(PyBytes_AS_STRING(result));

    // Perform resampling
    AudioResampler::Resample(src, src_frames, dst, dst_frames, channels, quality);

    PyBuffer_Release(&buffer);
    return result;
}

/**
 * Get detected CPU features
 *
 * Returns:
 *     dict: {"sse2": bool, "avx": bool, "avx2": bool}
 */
static PyObject* get_cpu_features(PyObject* self, PyObject* args) {
    PyObject* dict = PyDict_New();
    if (!dict) {
        return nullptr;
    }

    PyDict_SetItemString(dict, "sse2", CPUFeatures::HasSSE2() ? Py_True : Py_False);
    PyDict_SetItemString(dict, "avx", CPUFeatures::HasAVX() ? Py_True : Py_False);
    PyDict_SetItemString(dict, "avx2", CPUFeatures::HasAVX2() ? Py_True : Py_False);

    return dict;
}

/**
 * Detect audio format from PCM data
 *
 * Analyzes first few samples to determine if data is int16 or float32.
 * This is needed because WASAPI may return different formats than requested.
 *
 * Args:
 *     data (bytes): PCM audio data
 *
 * Returns:
 *     str: "int16", "float32", or "unknown"
 */
static PyObject* detect_format(PyObject* self, PyObject* args) {
    Py_buffer buffer;

    if (!PyArg_ParseTuple(args, "y*", &buffer)) {
        return nullptr;
    }

    // Need at least 400 bytes for reliable detection (100 samples)
    if (buffer.len < 400) {
        PyBuffer_Release(&buffer);
        return PyUnicode_FromString("unknown");
    }

    // Try float32 interpretation first
    if (buffer.len % 4 == 0) {
        const float* floats = static_cast<const float*>(buffer.buf);
        const size_t sample_count = std::min(buffer.len / 4, size_t(100));

        bool has_nan = false;
        bool has_inf = false;
        float max_abs = 0.0f;

        for (size_t i = 0; i < sample_count; ++i) {
            float val = floats[i];
            if (std::isnan(val)) {
                has_nan = true;
                break;
            }
            if (std::isinf(val)) {
                has_inf = true;
                break;
            }
            max_abs = std::max(max_abs, std::abs(val));
        }

        // Valid float32 audio is typically in [-1.0, 1.0] but allow up to 10.0
        if (!has_nan && !has_inf && max_abs > 0.0f && max_abs <= 10.0f) {
            PyBuffer_Release(&buffer);
            return PyUnicode_FromString("float32");
        }
    }

    // Try int16 interpretation
    if (buffer.len % 2 == 0) {
        const int16_t* int16s = static_cast<const int16_t*>(buffer.buf);
        const size_t sample_count = std::min(buffer.len / 2, size_t(100));

        int16_t max_abs = 0;
        for (size_t i = 0; i < sample_count; ++i) {
            int16_t val = int16s[i];
            if (std::abs(val) > max_abs) {
                max_abs = std::abs(val);
            }
        }

        // Has significant signal (>100 to avoid false positives)
        if (max_abs > 100) {
            PyBuffer_Release(&buffer);
            return PyUnicode_FromString("int16");
        }
    }

    PyBuffer_Release(&buffer);
    return PyUnicode_FromString("unknown");
}

/**
 * Check if high-quality resampling backend (libsamplerate) is available.
 *
 * Returns:
 *     bool: True if available, False otherwise
 */
static PyObject* is_high_quality_available(PyObject* self, PyObject* args) {
    if (AudioResampler::HasHighQualityBackend()) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

// Module methods
static PyMethodDef AudioConverterMethods[] = {
    {"convert_int16_to_float32", convert_int16_to_float32, METH_VARARGS,
     "Convert int16 PCM to float32 PCM with SIMD optimization"},
    {"resample_audio", resample_audio, METH_VARARGS,
     "Resample audio data with SIMD optimization"},
    {"get_cpu_features", get_cpu_features, METH_NOARGS,
     "Get detected CPU features (SSE2, AVX, AVX2)"},
    {"detect_format", detect_format, METH_VARARGS,
     "Detect audio format (int16 or float32) from PCM data"},
    {"is_high_quality_available", is_high_quality_available, METH_NOARGS,
     "Return True if libsamplerate backend is available"},
    {nullptr, nullptr, 0, nullptr}
};

// Module definition
static struct PyModuleDef audio_converter_module = {
    PyModuleDef_HEAD_INIT,
    "_audio_converter",
    "High-performance audio format converter with SIMD optimization",
    -1,
    AudioConverterMethods
};

// Module initializer
PyMODINIT_FUNC PyInit__audio_converter(void) {
    return PyModule_Create(&audio_converter_module);
}
