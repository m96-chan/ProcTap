/**
 * WASAPI Process Loopback Native Extension
 * VRChatプロセスのみの音声をキャプチャするC++拡張モジュール
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audiopolicy.h>
#include <functiondiscoverykeys_devpkey.h>
#include <combaseapi.h>
#include <objidl.h>
#include <wrl/client.h>
#include <vector>
#include <memory>
#include <string>

using Microsoft::WRL::ComPtr;

// ActivateAudioInterfaceAsync用のインターフェース (Windows 10 20H1+)
#include <mmdeviceapi.h>

// Windows SDK 10.0.22000以降で定義されている定数
#ifndef VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK
#define VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK L"VAD\\Process_Loopback"
#endif

// AUDIOCLIENT_ACTIVATION_TYPE
enum AUDIOCLIENT_ACTIVATION_TYPE {
    AUDIOCLIENT_ACTIVATION_TYPE_DEFAULT = 0,
    AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
};

// PROCESS_LOOPBACK_MODE
enum PROCESS_LOOPBACK_MODE {
    PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0,
    PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1
};

// アクティベーションパラメータ構造体
struct AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS {
    DWORD TargetProcessId;
    PROCESS_LOOPBACK_MODE ProcessLoopbackMode;
};

struct AUDIOCLIENT_ACTIVATION_PARAMS {
    AUDIOCLIENT_ACTIVATION_TYPE ActivationType;
    union {
        AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS ProcessLoopbackParams;
    };
};

// ActivateAudioInterfaceAsync関数のプロトタイプ
typedef HRESULT(WINAPI* PFN_ActivateAudioInterfaceAsync)(
    LPCWSTR deviceInterfacePath,
    REFIID riid,
    PROPVARIANT* activationParams,
    IActivateAudioInterfaceCompletionHandler* completionHandler,
    IActivateAudioInterfaceAsyncOperation** activationOperation
);

// コールバックハンドラークラス
// IAgileObjectを実装してスレッド間マーシャリングを可能にする
class AudioInterfaceActivationHandler : public IActivateAudioInterfaceCompletionHandler, public IAgileObject {
private:
    LONG m_refCount;
    HANDLE m_completionEvent;
    HRESULT m_activationResult;
    ComPtr<IUnknown> m_activatedInterface;

public:
    AudioInterfaceActivationHandler()
        : m_refCount(1)
        , m_activationResult(E_FAIL)
    {
        m_completionEvent = CreateEvent(nullptr, TRUE, FALSE, nullptr);
    }

    virtual ~AudioInterfaceActivationHandler() {
        if (m_completionEvent) {
            CloseHandle(m_completionEvent);
        }
    }

    // IUnknown methods
    STDMETHODIMP QueryInterface(REFIID riid, void** ppvObject) override {
        if (riid == __uuidof(IUnknown) ||
            riid == __uuidof(IActivateAudioInterfaceCompletionHandler)) {
            *ppvObject = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
            AddRef();
            return S_OK;
        }
        // IAgileObjectをサポート（スレッド間マーシャリング用）
        if (riid == __uuidof(IAgileObject)) {
            *ppvObject = static_cast<IAgileObject*>(this);
            AddRef();
            return S_OK;
        }
        *ppvObject = nullptr;
        return E_NOINTERFACE;
    }

    STDMETHODIMP_(ULONG) AddRef() override {
        return InterlockedIncrement(&m_refCount);
    }

    STDMETHODIMP_(ULONG) Release() override {
        LONG count = InterlockedDecrement(&m_refCount);
        if (count == 0) {
            delete this;
        }
        return count;
    }

    // IActivateAudioInterfaceCompletionHandler method
    STDMETHODIMP ActivateCompleted(IActivateAudioInterfaceAsyncOperation* operation) override {
        HRESULT hrActivateResult = E_FAIL;
        ComPtr<IUnknown> punkAudioInterface;

        HRESULT hr = operation->GetActivateResult(&hrActivateResult, &punkAudioInterface);

        m_activationResult = hrActivateResult;
        m_activatedInterface = punkAudioInterface;

        SetEvent(m_completionEvent);
        return S_OK;
    }

    // Helper methods
    HRESULT Wait(DWORD timeout = 5000) {
        if (WaitForSingleObject(m_completionEvent, timeout) != WAIT_OBJECT_0) {
            return E_FAIL;
        }
        return m_activationResult;
    }

    ComPtr<IUnknown> GetActivatedInterface() {
        return m_activatedInterface;
    }
};

// WASAPIプロセスループバッククラス
class WASAPIProcessCapture {
private:
    ComPtr<IAudioClient> m_audioClient;
    ComPtr<IAudioCaptureClient> m_captureClient;
    WAVEFORMATEX* m_waveFormat;
    HANDLE m_captureThread;
    HANDLE m_stopEvent;
    bool m_isCapturing;
    std::vector<BYTE> m_captureBuffer;
    CRITICAL_SECTION m_bufferLock;
    DWORD m_targetProcessId;
    bool m_isProcessSpecific;
    std::string m_lastError;

public:
    WASAPIProcessCapture()
        : m_waveFormat(nullptr)
        , m_captureThread(nullptr)
        , m_stopEvent(nullptr)
        , m_isCapturing(false)
        , m_targetProcessId(0)
        , m_isProcessSpecific(false)
    {
        InitializeCriticalSection(&m_bufferLock);
        m_stopEvent = CreateEvent(nullptr, TRUE, FALSE, nullptr);
    }

    ~WASAPIProcessCapture() {
        Cleanup();
        DeleteCriticalSection(&m_bufferLock);
        if (m_stopEvent) {
            CloseHandle(m_stopEvent);
        }
    }

    HRESULT InitializeForProcess(DWORD processId) {
        m_targetProcessId = processId;

        // ActivateAudioInterfaceAsyncはSTAスレッドで呼び出す必要がある
        // 既にCOMが初期化されている場合はRPC_E_CHANGED_MODEが返される
        HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        if (hr == RPC_E_CHANGED_MODE) {
            // 既に別のモードで初期化されている - これは許容される
            OutputDebugStringA("INFO: COM already initialized (possibly in different mode)\n");
            // STAモードかどうかは確認できないが、試してみる
        } else if (FAILED(hr)) {
            char errorMsg[256];
            sprintf_s(errorMsg, "ERROR: CoInitializeEx failed with HRESULT=0x%08X\n", hr);
            OutputDebugStringA(errorMsg);
            return hr;
        } else {
            OutputDebugStringA("INFO: COM initialized in STA mode\n");
        }

        // Windows 10 Build 20438以降が必要（プロセスループバックの最小要件）
        OSVERSIONINFOEXW osvi = {};
        osvi.dwOSVersionInfoSize = sizeof(osvi);
        osvi.dwMajorVersion = 10;
        osvi.dwMinorVersion = 0;
        osvi.dwBuildNumber = 20438; // Process Loopback minimum requirement

        DWORDLONG dwlConditionMask = 0;
        VER_SET_CONDITION(dwlConditionMask, VER_MAJORVERSION, VER_GREATER_EQUAL);
        VER_SET_CONDITION(dwlConditionMask, VER_MINORVERSION, VER_GREATER_EQUAL);
        VER_SET_CONDITION(dwlConditionMask, VER_BUILDNUMBER, VER_GREATER_EQUAL);

        if (!VerifyVersionInfoW(&osvi, VER_MAJORVERSION | VER_MINORVERSION | VER_BUILDNUMBER, dwlConditionMask)) {
            m_lastError = "Windows 10 Build 20438 or later is required for process-specific capture";
            OutputDebugStringA("WARNING: Windows 10 Build 20438 or later required for process-specific capture. Falling back to system-wide capture.\n");
            return InitializeSystemWide();
        }

        OutputDebugStringA("INFO: Attempting process-specific capture via ActivateAudioInterfaceAsync\n");

        // mmdevapi.dllをロード
        HMODULE hMmdevapi = LoadLibraryW(L"mmdevapi.dll");
        if (!hMmdevapi) {
            OutputDebugStringA("ERROR: Failed to load mmdevapi.dll\n");
            return InitializeSystemWide();
        }

        // ActivateAudioInterfaceAsync関数を取得
        PFN_ActivateAudioInterfaceAsync pfnActivateAudioInterfaceAsync =
            (PFN_ActivateAudioInterfaceAsync)GetProcAddress(hMmdevapi, "ActivateAudioInterfaceAsync");

        if (!pfnActivateAudioInterfaceAsync) {
            OutputDebugStringA("ERROR: ActivateAudioInterfaceAsync not found. Falling back to system-wide capture.\n");
            FreeLibrary(hMmdevapi);
            return InitializeSystemWide();
        }

        OutputDebugStringA("INFO: ActivateAudioInterfaceAsync found\n");

        // デバイスID: Microsoftの公式サンプルコードに従う
        const wchar_t* deviceId = VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK;

        // アクティベーションパラメータ（Microsoftの公式サンプルと完全に同じ方法）
        AUDIOCLIENT_ACTIVATION_PARAMS audioclientActivationParams = {};
        audioclientActivationParams.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
        audioclientActivationParams.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
        audioclientActivationParams.ProcessLoopbackParams.TargetProcessId = processId;

        // PROPVARIANTを初期化（Microsoftの公式サンプルと完全に同じ方法）
        PROPVARIANT activateParams = {};
        activateParams.vt = VT_BLOB;
        activateParams.blob.cbSize = sizeof(audioclientActivationParams);
        activateParams.blob.pBlobData = (BYTE*)&audioclientActivationParams;

        // コールバックハンドラーを作成
        AudioInterfaceActivationHandler* pHandler = new AudioInterfaceActivationHandler();
        if (!pHandler) {
            FreeLibrary(hMmdevapi);
            return E_OUTOFMEMORY;
        }

        ComPtr<IActivateAudioInterfaceAsyncOperation> pAsyncOp;

        // ActivateAudioInterfaceAsyncを呼び出し
        char debugMsg[512];
        sprintf_s(debugMsg, "INFO: Calling ActivateAudioInterfaceAsync for PID %lu\n", processId);
        OutputDebugStringA(debugMsg);

        hr = pfnActivateAudioInterfaceAsync(
            deviceId,
            __uuidof(IAudioClient),
            &activateParams,
            pHandler,
            &pAsyncOp
        );

        FreeLibrary(hMmdevapi);

        if (FAILED(hr)) {
            sprintf_s(debugMsg, "ERROR: ActivateAudioInterfaceAsync failed with HRESULT=0x%08X. Falling back to system-wide capture.\n", hr);
            OutputDebugStringA(debugMsg);
            char errorBuf[256];
            sprintf_s(errorBuf, "ActivateAudioInterfaceAsync failed with HRESULT=0x%08X", hr);
            m_lastError = errorBuf;
            pHandler->Release();
            return InitializeSystemWide();
        }

        OutputDebugStringA("INFO: Waiting for activation to complete...\n");

        // コールバック完了を待つ（タイムアウト10秒）
        hr = pHandler->Wait(10000);
        if (FAILED(hr)) {
            sprintf_s(debugMsg, "ERROR: Activation wait failed with HRESULT=0x%08X. Falling back to system-wide capture.\n", hr);
            OutputDebugStringA(debugMsg);
            char errorBuf[256];
            sprintf_s(errorBuf, "Activation wait failed with HRESULT=0x%08X", hr);
            m_lastError = errorBuf;
            pHandler->Release();
            return InitializeSystemWide();
        }

        OutputDebugStringA("INFO: Activation completed successfully\n");

        // IAudioClientを取得
        ComPtr<IUnknown> pUnknown = pHandler->GetActivatedInterface();
        pHandler->Release();

        if (!pUnknown) {
            OutputDebugStringA("ERROR: Failed to get activated interface. Falling back to system-wide capture.\n");
            return InitializeSystemWide();
        }

        hr = pUnknown.As(&m_audioClient);
        if (FAILED(hr)) {
            sprintf_s(debugMsg, "ERROR: Failed to query IAudioClient interface with HRESULT=0x%08X. Falling back to system-wide capture.\n", hr);
            OutputDebugStringA(debugMsg);
            return InitializeSystemWide();
        }

        OutputDebugStringA("INFO: Process-specific IAudioClient obtained successfully\n");
        m_isProcessSpecific = true;

        // プロセスループバックではGetMixFormat()がE_NOTIMPLを返すため、
        // Microsoftの公式サンプルに従ってハードコードされたフォーマットを使用
        m_waveFormat = (WAVEFORMATEX*)CoTaskMemAlloc(sizeof(WAVEFORMATEX));
        if (!m_waveFormat) {
            return E_OUTOFMEMORY;
        }

        // CD品質のPCMフォーマット (Microsoft公式サンプルと同じ)
        m_waveFormat->wFormatTag = WAVE_FORMAT_PCM;
        m_waveFormat->nChannels = 2;
        m_waveFormat->nSamplesPerSec = 44100;
        m_waveFormat->wBitsPerSample = 16;
        m_waveFormat->nBlockAlign = m_waveFormat->nChannels * m_waveFormat->wBitsPerSample / 8;
        m_waveFormat->nAvgBytesPerSec = m_waveFormat->nSamplesPerSec * m_waveFormat->nBlockAlign;
        m_waveFormat->cbSize = 0;

        OutputDebugStringA("INFO: Using hardcoded PCM format (44.1kHz, 16-bit, stereo)\n");

        // オーディオクライアントを初期化
        // AUDCLNT_STREAMFLAGS_EVENTCALLBACKは使わず、ポーリング方式で実装
        hr = m_audioClient->Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK,
            10000000, // 1秒
            0,
            m_waveFormat,
            nullptr
        );

        if (FAILED(hr)) {
            char errorMsg[256];
            sprintf_s(errorMsg, "ERROR: IAudioClient->Initialize failed with HRESULT=0x%08X\n", hr);
            OutputDebugStringA(errorMsg);
            return hr;
        }

        OutputDebugStringA("INFO: IAudioClient initialized successfully\n");

        // IAudioCaptureClientを取得
        hr = m_audioClient->GetService(__uuidof(IAudioCaptureClient), (void**)&m_captureClient);
        if (FAILED(hr)) {
            return hr;
        }

        return S_OK;
    }

    HRESULT InitializeSystemWide() {
        OutputDebugStringA("INFO: Initializing system-wide loopback capture\n");
        m_isProcessSpecific = false;

        // デバイス列挙子を作成
        ComPtr<IMMDeviceEnumerator> pEnumerator;
        HRESULT hr = CoCreateInstance(
            __uuidof(MMDeviceEnumerator),
            nullptr,
            CLSCTX_ALL,
            __uuidof(IMMDeviceEnumerator),
            (void**)&pEnumerator
        );

        if (FAILED(hr)) {
            OutputDebugStringA("ERROR: Failed to create device enumerator\n");
            return hr;
        }

        // デフォルトの再生デバイスを取得（ループバックモード用）
        ComPtr<IMMDevice> pDevice;
        hr = pEnumerator->GetDefaultAudioEndpoint(eRender, eConsole, &pDevice);
        if (FAILED(hr)) {
            OutputDebugStringA("ERROR: Failed to get default audio endpoint\n");
            return hr;
        }

        // IAudioClientをアクティベート
        hr = pDevice->Activate(
            __uuidof(IAudioClient),
            CLSCTX_ALL,
            nullptr,
            (void**)&m_audioClient
        );

        if (FAILED(hr)) {
            OutputDebugStringA("ERROR: Failed to activate IAudioClient\n");
            return hr;
        }

        OutputDebugStringA("INFO: System-wide IAudioClient activated successfully\n");

        // ミックスフォーマットを取得
        hr = m_audioClient->GetMixFormat(&m_waveFormat);
        if (FAILED(hr)) {
            return hr;
        }

        // オーディオクライアントを初期化
        hr = m_audioClient->Initialize(
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
            10000000, // 1秒
            0,
            m_waveFormat,
            nullptr
        );

        if (FAILED(hr)) {
            return hr;
        }

        // IAudioCaptureClientを取得
        hr = m_audioClient->GetService(__uuidof(IAudioCaptureClient), (void**)&m_captureClient);
        if (FAILED(hr)) {
            return hr;
        }

        return S_OK;
    }

    HRESULT StartCapture() {
        if (m_isCapturing) {
            return S_OK;
        }

        HRESULT hr = m_audioClient->Start();
        if (FAILED(hr)) {
            return hr;
        }

        m_isCapturing = true;
        ResetEvent(m_stopEvent);

        return S_OK;
    }

    HRESULT StopCapture() {
        if (!m_isCapturing) {
            return S_OK;
        }

        SetEvent(m_stopEvent);
        m_isCapturing = false;

        if (m_audioClient) {
            m_audioClient->Stop();
        }

        return S_OK;
    }

    HRESULT ReadData(BYTE** ppData, UINT32* pDataSize) {
        if (!m_isCapturing || !m_captureClient) {
            return E_FAIL;
        }

        UINT32 packetLength = 0;
        HRESULT hr = m_captureClient->GetNextPacketSize(&packetLength);
        if (FAILED(hr) || packetLength == 0) {
            *ppData = nullptr;
            *pDataSize = 0;
            return S_FALSE;
        }

        BYTE* pData = nullptr;
        UINT32 numFramesAvailable = 0;
        DWORD flags = 0;

        hr = m_captureClient->GetBuffer(&pData, &numFramesAvailable, &flags, nullptr, nullptr);
        if (FAILED(hr)) {
            return hr;
        }

        UINT32 dataSize = numFramesAvailable * m_waveFormat->nBlockAlign;

        // データをコピー
        EnterCriticalSection(&m_bufferLock);
        size_t oldSize = m_captureBuffer.size();
        m_captureBuffer.resize(oldSize + dataSize);
        memcpy(m_captureBuffer.data() + oldSize, pData, dataSize);
        LeaveCriticalSection(&m_bufferLock);

        m_captureClient->ReleaseBuffer(numFramesAvailable);

        *ppData = nullptr;
        *pDataSize = 0;
        return S_OK;
    }

    HRESULT GetBufferedData(BYTE** ppData, UINT32* pDataSize) {
        EnterCriticalSection(&m_bufferLock);

        if (m_captureBuffer.empty()) {
            *ppData = nullptr;
            *pDataSize = 0;
            LeaveCriticalSection(&m_bufferLock);
            return S_FALSE;
        }

        *pDataSize = (UINT32)m_captureBuffer.size();
        *ppData = (BYTE*)PyMem_Malloc(*pDataSize);

        if (*ppData) {
            memcpy(*ppData, m_captureBuffer.data(), *pDataSize);
            m_captureBuffer.clear();
        }

        LeaveCriticalSection(&m_bufferLock);
        return S_OK;
    }

    WAVEFORMATEX* GetWaveFormat() {
        return m_waveFormat;
    }

    bool IsProcessSpecific() {
        return m_isProcessSpecific;
    }

    const char* GetLastError() {
        return m_lastError.c_str();
    }

    void Cleanup() {
        StopCapture();
        m_captureClient.Reset();
        m_audioClient.Reset();

        if (m_waveFormat) {
            CoTaskMemFree(m_waveFormat);
            m_waveFormat = nullptr;
        }

        EnterCriticalSection(&m_bufferLock);
        m_captureBuffer.clear();
        LeaveCriticalSection(&m_bufferLock);
    }
};

// Python拡張モジュールの実装

typedef struct {
    PyObject_HEAD
    WASAPIProcessCapture* capture;
} ProcessLoopbackObject;

static void ProcessLoopback_dealloc(ProcessLoopbackObject* self) {
    if (self->capture) {
        delete self->capture;
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject* ProcessLoopback_new(PyTypeObject* type, PyObject* args, PyObject* kwds) {
    ProcessLoopbackObject* self = (ProcessLoopbackObject*)type->tp_alloc(type, 0);
    if (self != nullptr) {
        self->capture = new WASAPIProcessCapture();
    }
    return (PyObject*)self;
}

static int ProcessLoopback_init(ProcessLoopbackObject* self, PyObject* args, PyObject* kwds) {
    unsigned long processId = 0;

    if (!PyArg_ParseTuple(args, "k", &processId)) {
        return -1;
    }

    // プロセスIDの警告を出力
    char msg[256];
    sprintf_s(msg, "WARNING: Process-specific loopback (PID: %lu) is not yet fully implemented. Using system-wide capture.\n", processId);
    OutputDebugStringA(msg);

    // まずはプロセス別初期化を試みる
    HRESULT hr = self->capture->InitializeForProcess(processId);
    if (FAILED(hr)) {
        // エラーメッセージを詳細に
        char error_msg[512];
        sprintf_s(error_msg, "Failed to initialize process loopback (HRESULT=0x%08X). This feature requires Windows 10 20H1 or later.", hr);
        PyErr_SetString(PyExc_RuntimeError, error_msg);
        return -1;
    }

    return 0;
}

static PyObject* ProcessLoopback_start(ProcessLoopbackObject* self, PyObject* Py_UNUSED(ignored)) {
    HRESULT hr = self->capture->StartCapture();
    if (FAILED(hr)) {
        PyErr_Format(PyExc_RuntimeError, "Failed to start capture: HRESULT=0x%08X", hr);
        return nullptr;
    }
    Py_RETURN_NONE;
}

static PyObject* ProcessLoopback_stop(ProcessLoopbackObject* self, PyObject* Py_UNUSED(ignored)) {
    HRESULT hr = self->capture->StopCapture();
    if (FAILED(hr)) {
        PyErr_Format(PyExc_RuntimeError, "Failed to stop capture: HRESULT=0x%08X", hr);
        return nullptr;
    }
    Py_RETURN_NONE;
}

static PyObject* ProcessLoopback_read(ProcessLoopbackObject* self, PyObject* Py_UNUSED(ignored)) {
    BYTE* pData = nullptr;
    UINT32 dataSize = 0;

    // バッファからデータを読み取る
    HRESULT hr = self->capture->ReadData(&pData, &dataSize);
    if (FAILED(hr)) {
        PyErr_Format(PyExc_RuntimeError, "Failed to read data: HRESULT=0x%08X", hr);
        return nullptr;
    }

    // 蓄積されたデータを取得
    hr = self->capture->GetBufferedData(&pData, &dataSize);
    if (hr == S_FALSE || dataSize == 0) {
        Py_RETURN_NONE;
    }

    PyObject* result = PyBytes_FromStringAndSize((const char*)pData, dataSize);
    PyMem_Free(pData);

    return result;
}

static PyObject* ProcessLoopback_get_format(ProcessLoopbackObject* self, PyObject* Py_UNUSED(ignored)) {
    WAVEFORMATEX* fmt = self->capture->GetWaveFormat();
    if (!fmt) {
        Py_RETURN_NONE;
    }

    return Py_BuildValue("{s:i,s:i,s:i,s:i}",
        "channels", fmt->nChannels,
        "sample_rate", fmt->nSamplesPerSec,
        "bits_per_sample", fmt->wBitsPerSample,
        "block_align", fmt->nBlockAlign
    );
}

static PyObject* ProcessLoopback_is_process_specific(ProcessLoopbackObject* self, PyObject* Py_UNUSED(ignored)) {
    bool isProcessSpecific = self->capture->IsProcessSpecific();
    return PyBool_FromLong(isProcessSpecific ? 1 : 0);
}

static PyObject* ProcessLoopback_get_last_error(ProcessLoopbackObject* self, PyObject* Py_UNUSED(ignored)) {
    const char* lastError = self->capture->GetLastError();
    if (lastError && lastError[0] != '\0') {
        return PyUnicode_FromString(lastError);
    }
    Py_RETURN_NONE;
}

static PyMethodDef ProcessLoopback_methods[] = {
    {"start", (PyCFunction)ProcessLoopback_start, METH_NOARGS, "Start audio capture"},
    {"stop", (PyCFunction)ProcessLoopback_stop, METH_NOARGS, "Stop audio capture"},
    {"read", (PyCFunction)ProcessLoopback_read, METH_NOARGS, "Read captured audio data"},
    {"get_format", (PyCFunction)ProcessLoopback_get_format, METH_NOARGS, "Get audio format info"},
    {"is_process_specific", (PyCFunction)ProcessLoopback_is_process_specific, METH_NOARGS, "Check if process-specific capture is active"},
    {"get_last_error", (PyCFunction)ProcessLoopback_get_last_error, METH_NOARGS, "Get last error message"},
    {nullptr, nullptr, 0, nullptr}
};

static PyTypeObject ProcessLoopbackType = {
    PyVarObject_HEAD_INIT(nullptr, 0)
    /* tp_name */ processaudiotap._native.ProcessLoopback,
    /* tp_basicsize */ sizeof(ProcessLoopbackObject),
    /* tp_itemsize */ 0,
    /* tp_dealloc */ (destructor)ProcessLoopback_dealloc,
    /* tp_vectorcall_offset */ 0,
    /* tp_getattr */ nullptr,
    /* tp_setattr */ nullptr,
    /* tp_as_async */ nullptr,
    /* tp_repr */ nullptr,
    /* tp_as_number */ nullptr,
    /* tp_as_sequence */ nullptr,
    /* tp_as_mapping */ nullptr,
    /* tp_hash */ nullptr,
    /* tp_call */ nullptr,
    /* tp_str */ nullptr,
    /* tp_getattro */ nullptr,
    /* tp_setattro */ nullptr,
    /* tp_as_buffer */ nullptr,
    /* tp_flags */ Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    /* tp_doc */ "WASAPI Process Loopback Capture",
    /* tp_traverse */ nullptr,
    /* tp_clear */ nullptr,
    /* tp_richcompare */ nullptr,
    /* tp_weaklistoffset */ 0,
    /* tp_iter */ nullptr,
    /* tp_iternext */ nullptr,
    /* tp_methods */ ProcessLoopback_methods,
    /* tp_members */ nullptr,
    /* tp_getset */ nullptr,
    /* tp_base */ nullptr,
    /* tp_dict */ nullptr,
    /* tp_descr_get */ nullptr,
    /* tp_descr_set */ nullptr,
    /* tp_dictoffset */ 0,
    /* tp_init */ (initproc)ProcessLoopback_init,
    /* tp_alloc */ nullptr,
    /* tp_new */ ProcessLoopback_new,
};

// Module definition
static struct PyModuleDef wasapi_module = {
    PyModuleDef_HEAD_INIT,
    "_native",
    "ProcessAudioTap native WASAPI backend (WASAPI per-process loopback)",
    -1,
    nullptr,  // no global module-level functions for now
    nullptr,
    nullptr,
    nullptr,
    nullptr
};

// Module initializer
PyMODINIT_FUNC PyInit__native(void)
{
    PyObject* m;

    // Prepare Python type object
    if (PyType_Ready(&ProcessLoopbackType) < 0) {
        return nullptr;
    }

    // Create module object
    m = PyModule_Create(&wasapi_module);
    if (m == nullptr) {
        return nullptr;
    }

    // Add ProcessLoopback type to module
    Py_INCREF(&ProcessLoopbackType);
    if (PyModule_AddObject(m, "ProcessLoopback", (PyObject*)&ProcessLoopbackType) < 0) {
        Py_DECREF(&ProcessLoopbackType);
        Py_DECREF(m);
        return nullptr;
    }

    return m;
}
