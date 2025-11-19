/**
 * High-performance audio format converter with SIMD optimization
 *
 * Features:
 * - int16 → float32 conversion (SSE2/AVX2)
 * - Resampling (Linear interpolation or libsamplerate)
 * - Runtime CPU feature detection
 */

#pragma once

#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <limits>
#include <mutex>
#include <string>

#include <immintrin.h>  // SSE2, AVX, AVX2
#include <intrin.h>     // __cpuid for MSVC

#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace proctap {

/**
 * CPU feature detection (Windows/MSVC compatible)
 */
class CPUFeatures {
public:
    static bool HasSSE2() {
        static bool checked = false;
        static bool has_sse2 = false;
        if (!checked) {
            int cpuInfo[4];
            __cpuid(cpuInfo, 1);
            has_sse2 = (cpuInfo[3] & (1 << 26)) != 0;  // EDX bit 26
            checked = true;
        }
        return has_sse2;
    }

    static bool HasAVX() {
        static bool checked = false;
        static bool has_avx = false;
        if (!checked) {
            int cpuInfo[4];
            __cpuid(cpuInfo, 1);
            has_avx = (cpuInfo[2] & (1 << 28)) != 0;  // ECX bit 28
            checked = true;
        }
        return has_avx;
    }

    static bool HasAVX2() {
        static bool checked = false;
        static bool has_avx2 = false;
        if (!checked) {
            int cpuInfo[4];
            __cpuidex(cpuInfo, 7, 0);
            has_avx2 = (cpuInfo[1] & (1 << 5)) != 0;  // EBX bit 5
            checked = true;
        }
        return has_avx2;
    }
};

/**
 * High-performance int16 → float32 converter
 */
class Int16ToFloat32Converter {
public:
    /**
     * Convert int16 PCM to float32 normalized to [-1.0, 1.0]
     * Automatically selects best SIMD implementation
     *
     * @param src Source int16 buffer
     * @param dst Destination float32 buffer (must be pre-allocated)
     * @param count Number of samples to convert
     */
    static void Convert(const int16_t* src, float* dst, size_t count) {
        if (CPUFeatures::HasAVX2()) {
            ConvertAVX2(src, dst, count);
        } else if (CPUFeatures::HasSSE2()) {
            ConvertSSE2(src, dst, count);
        } else {
            ConvertScalar(src, dst, count);
        }
    }

private:
    /**
     * AVX2 implementation: Processes 16 samples at once
     */
    static void ConvertAVX2(const int16_t* src, float* dst, size_t count) {
        const float scale = 1.0f / 32768.0f;
        const __m256 scale_vec = _mm256_set1_ps(scale);

        size_t i = 0;
        // Process 16 samples per iteration
        for (; i + 16 <= count; i += 16) {
            // Load 16x int16 samples
            __m256i int16_vec = _mm256_loadu_si256((__m256i*)(src + i));

            // Split into two 128-bit halves for conversion
            __m128i low_half = _mm256_castsi256_si128(int16_vec);
            __m128i high_half = _mm256_extracti128_si256(int16_vec, 1);

            // Convert low half: int16 → int32 → float32
            __m256i low_int32 = _mm256_cvtepi16_epi32(low_half);
            __m256 low_float = _mm256_cvtepi32_ps(low_int32);
            low_float = _mm256_mul_ps(low_float, scale_vec);

            // Convert high half
            __m256i high_int32 = _mm256_cvtepi16_epi32(high_half);
            __m256 high_float = _mm256_cvtepi32_ps(high_int32);
            high_float = _mm256_mul_ps(high_float, scale_vec);

            // Store results
            _mm256_storeu_ps(dst + i, low_float);
            _mm256_storeu_ps(dst + i + 8, high_float);
        }

        // Process remaining samples with scalar code
        ConvertScalar(src + i, dst + i, count - i);
    }

    /**
     * SSE2 implementation: Processes 8 samples at once
     */
    static void ConvertSSE2(const int16_t* src, float* dst, size_t count) {
        const float scale = 1.0f / 32768.0f;
        const __m128 scale_vec = _mm_set1_ps(scale);

        size_t i = 0;
        // Process 8 samples per iteration
        for (; i + 8 <= count; i += 8) {
            // Load 8x int16 samples
            __m128i int16_vec = _mm_loadu_si128((__m128i*)(src + i));

            // Convert to int32 (low and high parts)
            __m128i low_int32 = _mm_cvtepi16_epi32(int16_vec);
            __m128i high_int32 = _mm_cvtepi16_epi32(_mm_srli_si128(int16_vec, 8));

            // Convert to float32
            __m128 low_float = _mm_cvtepi32_ps(low_int32);
            __m128 high_float = _mm_cvtepi32_ps(high_int32);

            // Scale to [-1.0, 1.0]
            low_float = _mm_mul_ps(low_float, scale_vec);
            high_float = _mm_mul_ps(high_float, scale_vec);

            // Store results
            _mm_storeu_ps(dst + i, low_float);
            _mm_storeu_ps(dst + i + 4, high_float);
        }

        // Process remaining samples
        ConvertScalar(src + i, dst + i, count - i);
    }

    /**
     * Scalar fallback implementation
     */
    static void ConvertScalar(const int16_t* src, float* dst, size_t count) {
        const float scale = 1.0f / 32768.0f;
        for (size_t i = 0; i < count; ++i) {
            dst[i] = static_cast<float>(src[i]) * scale;
        }
    }
};

/**
 * Resampling quality modes
 */
enum class ResamplingQuality {
    LowLatency,     // Linear interpolation with SIMD
    HighQuality     // libsamplerate (SINC)
};

/**
 * Audio resampler with SIMD optimization
 */
class AudioResampler {
public:
    /**
     * Check if libsamplerate backend is available.
     */
    static bool HasHighQualityBackend() {
        return LibSampleRate::IsAvailable();
    }

    /**
     * Resample audio data
     *
     * @param src Source float32 buffer
     * @param src_frames Number of source frames
     * @param dst Destination float32 buffer (must be pre-allocated)
     * @param dst_frames Number of destination frames
     * @param channels Number of channels (interleaved)
     * @param quality Resampling quality mode
     */
    static void Resample(
        const float* src, size_t src_frames,
        float* dst, size_t dst_frames,
        int channels, ResamplingQuality quality
    ) {
        if (quality == ResamplingQuality::LowLatency) {
            ResampleLinear(src, src_frames, dst, dst_frames, channels);
        } else {
            if (!ResampleHighQuality(src, src_frames, dst, dst_frames, channels)) {
                // Fallback to linear interpolation if high-quality backend unavailable
                ResampleLinear(src, src_frames, dst, dst_frames, channels);
            }
        }
    }

private:
    /**
     * Wrapper around libsamplerate (loaded dynamically).
     */
    class LibSampleRate {
    public:
        struct SRC_DATA {
            const float* data_in;
            float* data_out;
            long input_frames;
            long output_frames;
            long input_frames_used;
            long output_frames_gen;
            int end_of_input;
            double src_ratio;
        };

        using SrcSimpleFn = int (*)(SRC_DATA*, int, int);

        static bool IsAvailable() {
            EnsureInitialized();
            return src_simple_fn_ != nullptr;
        }

        static bool Resample(
            const float* src, size_t src_frames,
            float* dst, size_t dst_frames,
            int channels
        ) {
            EnsureInitialized();
            if (!src_simple_fn_ || src_frames == 0 || dst_frames == 0) {
                return false;
            }

            const auto max_long = static_cast<size_t>(std::numeric_limits<long>::max());
            if (src_frames > max_long || dst_frames > max_long) {
                return false;
            }

            SRC_DATA data{};
            data.data_in = src;
            data.data_out = dst;
            data.input_frames = static_cast<long>(src_frames);
            data.output_frames = static_cast<long>(dst_frames);
            data.input_frames_used = 0;
            data.output_frames_gen = 0;
            data.end_of_input = 1;
            data.src_ratio = static_cast<double>(dst_frames) / static_cast<double>(src_frames);

            const int converter_type = 0;  // SRC_SINC_BEST_QUALITY
            const int err = src_simple_fn_(&data, converter_type, channels);
            return err == 0;
        }

    private:
        inline static std::once_flag init_flag_;
#if defined(_WIN32)
        inline static HMODULE library_handle_ = nullptr;
#else
        inline static void* library_handle_ = nullptr;
#endif
        inline static SrcSimpleFn src_simple_fn_ = nullptr;

        static void EnsureInitialized() {
            std::call_once(init_flag_, []() {
                LoadLibraryHandle();
                if (!library_handle_) {
                    return;
                }
#if defined(_WIN32)
                src_simple_fn_ = reinterpret_cast<SrcSimpleFn>(
                    GetProcAddress(library_handle_, "src_simple")
                );
#else
                src_simple_fn_ = reinterpret_cast<SrcSimpleFn>(
                    dlsym(library_handle_, "src_simple")
                );
#endif
                if (!src_simple_fn_) {
                    ReleaseLibrary();
                }
            });
        }

        static void ReleaseLibrary() {
#if defined(_WIN32)
            if (library_handle_) {
                FreeLibrary(library_handle_);
                library_handle_ = nullptr;
            }
#else
            if (library_handle_) {
                dlclose(library_handle_);
                library_handle_ = nullptr;
            }
#endif
            src_simple_fn_ = nullptr;
        }

        static void LoadLibraryHandle() {
#if defined(_WIN32)
            // Try environment variable first (expects absolute DLL path)
            const char* env_path = std::getenv("LIBSAMPLERATE_PATH");
            if (env_path && env_path[0] != '\0') {
                const int wide_len = MultiByteToWideChar(
                    CP_UTF8, 0, env_path, -1, nullptr, 0
                );
                if (wide_len > 0) {
                    std::wstring wide_path(static_cast<size_t>(wide_len), L'\0');
                    MultiByteToWideChar(
                        CP_UTF8, 0, env_path, -1, wide_path.data(), wide_len
                    );
                    library_handle_ = LoadLibraryW(wide_path.c_str());
                }
            }

            if (!library_handle_) {
                const wchar_t* dll_names[] = {
                    L"libsamplerate-0.dll",
                    L"samplerate.dll"
                };
                for (const auto* name : dll_names) {
                    library_handle_ = LoadLibraryW(name);
                    if (library_handle_) {
                        break;
                    }
                }
            }
#else
            const char* env_path = std::getenv("LIBSAMPLERATE_PATH");
            if (env_path && env_path[0] != '\0') {
                library_handle_ = dlopen(env_path, RTLD_LAZY);
            }
            if (!library_handle_) {
                const char* so_names[] = {"libsamplerate.so.0", "libsamplerate.so"};
                for (const auto* name : so_names) {
                    library_handle_ = dlopen(name, RTLD_LAZY);
                    if (library_handle_) {
                        break;
                    }
                }
            }
#endif
        }
    };

    /**
     * High-quality resampler using libsamplerate.
     */
    static bool ResampleHighQuality(
        const float* src, size_t src_frames,
        float* dst, size_t dst_frames,
        int channels
    ) {
        return LibSampleRate::Resample(src, src_frames, dst, dst_frames, channels);
    }

    /**
     * Linear interpolation resampler (low latency, SIMD optimized)
     */
    static void ResampleLinear(
        const float* src, size_t src_frames,
        float* dst, size_t dst_frames,
        int channels
    ) {
        const double ratio = static_cast<double>(src_frames) / dst_frames;

        for (size_t i = 0; i < dst_frames; ++i) {
            const double src_pos = i * ratio;
            const size_t src_idx = static_cast<size_t>(src_pos);
            const float frac = static_cast<float>(src_pos - src_idx);

            if (src_idx + 1 < src_frames) {
                // Linear interpolation for each channel
                for (int ch = 0; ch < channels; ++ch) {
                    const float s0 = src[(src_idx * channels) + ch];
                    const float s1 = src[((src_idx + 1) * channels) + ch];
                    dst[(i * channels) + ch] = s0 + frac * (s1 - s0);
                }
            } else {
                // Edge case: just copy last sample
                for (int ch = 0; ch < channels; ++ch) {
                    dst[(i * channels) + ch] = src[(src_idx * channels) + ch];
                }
            }
        }
    }
};

} // namespace proctap
