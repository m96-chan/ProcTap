#!/usr/bin/env python3
"""
WASAPI Process Loopback Capture
Windows Audio Session APIを直接使用してプロセス別の音声をキャプチャ
"""
import logging
import struct
import time
import threading
from ctypes import POINTER, cast, c_float
from typing import Optional

try:
    import comtypes
    from comtypes import GUID, IUnknown
    WASAPI_AVAILABLE = True
except ImportError as e:
    WASAPI_AVAILABLE = False
    logging.warning(f"comtypesが利用できません: {e}")

# CLSCTX_ALL定数
CLSCTX_ALL = 23

logger = logging.getLogger(__name__)

# WASAPI定数
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000

# オーディオクライアント共有モード
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_SHAREMODE_EXCLUSIVE = 1

# REFERENCE_TIME = 100ナノ秒単位
REFTIMES_PER_SEC = 10000000
REFTIMES_PER_MILLISEC = 10000

# AudioClient StreamOptions (Windows 10 1803+)
AUDCLNT_STREAMOPTIONS_NONE = 0
AUDCLNT_STREAMOPTIONS_RAW = 0x1
AUDCLNT_STREAMOPTIONS_MATCH_FORMAT = 0x2

# Process Loopback Mode (Windows 10 20H1+)
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1

# AUDIOCLIENT_ACTIVATION_TYPE
AUDIOCLIENT_ACTIVATION_TYPE_DEFAULT = 0
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1


class WAVEFORMATEX(comtypes.Structure):
    """WAVEFORMATEXフォーマット構造体"""
    _fields_ = [
        ('wFormatTag', comtypes.c_uint16),
        ('nChannels', comtypes.c_uint16),
        ('nSamplesPerSec', comtypes.c_uint32),
        ('nAvgBytesPerSec', comtypes.c_uint32),
        ('nBlockAlign', comtypes.c_uint16),
        ('wBitsPerSample', comtypes.c_uint16),
        ('cbSize', comtypes.c_uint16),
    ]


class AudioClientProperties(comtypes.Structure):
    """AudioClientPropertiesプロパティ構造体"""
    _fields_ = [
        ('cbSize', comtypes.c_uint32),
        ('bIsOffload', comtypes.c_bool),
        ('eCategory', comtypes.c_int),  # AUDIO_STREAM_CATEGORY
        ('Options', comtypes.c_uint32),  # AUDCLNT_STREAMOPTIONS
    ]


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(comtypes.Structure):
    """プロセスループバックパラメータ"""
    _fields_ = [
        ('TargetProcessId', comtypes.c_uint32),
        ('ProcessLoopbackMode', comtypes.c_uint32),
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(comtypes.Structure):
    """オーディオクライアントアクティベーションパラメータ"""
    _fields_ = [
        ('ActivationType', comtypes.c_int),  # AUDIOCLIENT_ACTIVATION_TYPE
        ('ProcessLoopbackParams', AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


# IAudioClient GUID
IID_IAudioClient = GUID('{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}')


class IAudioClient(IUnknown):
    """IAudioClientインターフェース"""
    _iid_ = IID_IAudioClient
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'Initialize',
                          [comtypes.c_int,  # ShareMode
                           comtypes.c_uint32,  # StreamFlags
                           comtypes.c_int64,  # hnsBufferDuration
                           comtypes.c_int64,  # hnsPeriodicity
                           POINTER(WAVEFORMATEX),  # pFormat
                           POINTER(GUID)]),  # AudioSessionGuid
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetBufferSize',
                          [POINTER(comtypes.c_uint32)]),  # pNumBufferFrames
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetStreamLatency',
                          [POINTER(comtypes.c_int64)]),  # phnsLatency
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetCurrentPadding',
                          [POINTER(comtypes.c_uint32)]),  # pNumPaddingFrames
        comtypes.STDMETHOD(comtypes.HRESULT, 'IsFormatSupported',
                          [comtypes.c_int,  # ShareMode
                           POINTER(WAVEFORMATEX),  # pFormat
                           POINTER(POINTER(WAVEFORMATEX))]),  # ppClosestMatch
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetMixFormat',
                          [POINTER(POINTER(WAVEFORMATEX))]),  # ppDeviceFormat
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetDevicePeriod',
                          [POINTER(comtypes.c_int64),  # phnsDefaultDevicePeriod
                           POINTER(comtypes.c_int64)]),  # phnsMinimumDevicePeriod
        comtypes.STDMETHOD(comtypes.HRESULT, 'Start'),
        comtypes.STDMETHOD(comtypes.HRESULT, 'Stop'),
        comtypes.STDMETHOD(comtypes.HRESULT, 'Reset'),
        comtypes.STDMETHOD(comtypes.HRESULT, 'SetEventHandle',
                          [comtypes.c_void_p]),  # eventHandle
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetService',
                          [POINTER(GUID),  # riid
                           POINTER(POINTER(IUnknown))]),  # ppv
    ]


# IAudioClient2 GUID (Windows 8+)
IID_IAudioClient2 = GUID('{726778CD-F60A-4EDA-82DE-E47610CD78AA}')


class IAudioClient2(IAudioClient):
    """IAudioClient2インターフェース (Windows 8+)"""
    _iid_ = IID_IAudioClient2
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'SetClientProperties',
                          [POINTER(AudioClientProperties)]),  # pProperties
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetBufferSizeLimits',
                          [POINTER(WAVEFORMATEX),  # pFormat
                           comtypes.c_bool,  # bEventDriven
                           POINTER(comtypes.c_int64),  # phnsMinBufferDuration
                           POINTER(comtypes.c_int64)]),  # phnsMaxBufferDuration
    ]


# IAudioClient3 GUID (Windows 10+)
IID_IAudioClient3 = GUID('{7ED4EE07-8E67-4CD4-8C1A-2B7A5987AD42}')


class IAudioClient3(IAudioClient2):
    """IAudioClient3インターフェース (Windows 10+)"""
    _iid_ = IID_IAudioClient3
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetSharedModeEnginePeriod',
                          [POINTER(WAVEFORMATEX),  # pFormat
                           POINTER(comtypes.c_uint32),  # pDefaultPeriodInFrames
                           POINTER(comtypes.c_uint32),  # pFundamentalPeriodInFrames
                           POINTER(comtypes.c_uint32),  # pMinPeriodInFrames
                           POINTER(comtypes.c_uint32)]),  # pMaxPeriodInFrames
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetCurrentSharedModeEnginePeriod',
                          [POINTER(POINTER(WAVEFORMATEX)),  # ppFormat
                           POINTER(comtypes.c_uint32)]),  # pCurrentPeriodInFrames
        comtypes.STDMETHOD(comtypes.HRESULT, 'InitializeSharedAudioStream',
                          [comtypes.c_uint32,  # StreamFlags
                           comtypes.c_uint32,  # PeriodInFrames
                           POINTER(WAVEFORMATEX),  # pFormat
                           POINTER(GUID)]),  # AudioSessionGuid
    ]


# IMMDevice GUID
IID_IMMDevice = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')


class IMMDevice(IUnknown):
    """IMMDeviceインターフェース"""
    _iid_ = IID_IMMDevice
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'Activate',
                          [POINTER(GUID),  # iid
                           comtypes.c_uint32,  # dwClsCtx
                           POINTER(comtypes.c_int),  # pActivationParams
                           POINTER(POINTER(IUnknown))]),  # ppInterface
        comtypes.STDMETHOD(comtypes.HRESULT, 'OpenPropertyStore',
                          [comtypes.c_uint32,  # stgmAccess
                           POINTER(POINTER(IUnknown))]),  # ppProperties
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetId',
                          [POINTER(comtypes.c_wchar_p)]),  # ppstrId
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetState',
                          [POINTER(comtypes.c_uint32)]),  # pdwState
    ]


# IMMDeviceEnumerator GUID
IID_IMMDeviceEnumerator = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
CLSID_MMDeviceEnumerator = GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}')


class IMMDeviceEnumerator(IUnknown):
    """IMMDeviceEnumeratorインターフェース"""
    _iid_ = IID_IMMDeviceEnumerator
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'EnumAudioEndpoints',
                          [comtypes.c_int,  # dataFlow
                           comtypes.c_uint32,  # dwStateMask
                           POINTER(POINTER(IUnknown))]),  # ppDevices
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetDefaultAudioEndpoint',
                          [comtypes.c_int,  # dataFlow (eRender=0, eCapture=1)
                           comtypes.c_int,  # role (eConsole=0)
                           POINTER(POINTER(IMMDevice))]),  # ppEndpoint
    ]


# IActivateAudioInterfaceCompletionHandler GUID
IID_IActivateAudioInterfaceCompletionHandler = GUID('{41D949AB-9862-444A-80F6-C261334DA5EB}')


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    """IActivateAudioInterfaceAsyncOperationインターフェース"""
    _iid_ = GUID('{72A22D78-CDE4-431D-B8CC-843A71199B6D}')
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetActivateResult',
                          [POINTER(comtypes.HRESULT),  # activateResult
                           POINTER(POINTER(IUnknown))]),  # activatedInterface
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    """IActivateAudioInterfaceCompletionHandlerインターフェース"""
    _iid_ = IID_IActivateAudioInterfaceCompletionHandler
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'ActivateCompleted',
                          [POINTER(IActivateAudioInterfaceAsyncOperation)]),  # activateOperation
    ]


# IAudioCaptureClient GUID
IID_IAudioCaptureClient = GUID('{C8ADBD64-E71E-48a0-A4DE-185C395CD317}')


class IAudioCaptureClient(IUnknown):
    """IAudioCaptureClientインターフェース"""
    _iid_ = IID_IAudioCaptureClient
    _methods_ = [
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetBuffer',
                          [POINTER(POINTER(comtypes.c_byte)),  # ppData
                           POINTER(comtypes.c_uint32),  # pNumFramesToRead
                           POINTER(comtypes.c_uint32),  # pdwFlags
                           POINTER(comtypes.c_uint64),  # pu64DevicePosition
                           POINTER(comtypes.c_uint64)]),  # pu64QPCPosition
        comtypes.STDMETHOD(comtypes.HRESULT, 'ReleaseBuffer',
                          [comtypes.c_uint32]),  # NumFramesRead
        comtypes.STDMETHOD(comtypes.HRESULT, 'GetNextPacketSize',
                          [POINTER(comtypes.c_uint32)]),  # pNumFramesInNextPacket
    ]


class AudioInterfaceActivationHandler(comtypes.COMObject):
    """ActivateAudioInterfaceAsync用のコールバックハンドラー"""
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler]

    def __init__(self):
        super().__init__()
        self.activation_result = None
        self.activated_interface = None
        self.completion_event = threading.Event()

    def IActivateAudioInterfaceCompletionHandler_ActivateCompleted(self, activate_operation):
        """アクティベーション完了コールバック"""
        try:
            hr = comtypes.HRESULT()
            interface_ptr = POINTER(IUnknown)()

            result = activate_operation.GetActivateResult(
                comtypes.byref(hr),
                comtypes.byref(interface_ptr)
            )

            self.activation_result = hr.value
            self.activated_interface = interface_ptr

            logger.info(f"オーディオインターフェースのアクティベーション完了: hr={hr.value}")

        except Exception as e:
            logger.error(f"アクティベーションコールバックエラー: {e}")
            self.activation_result = -1

        finally:
            self.completion_event.set()

        return 0  # S_OK


class WASAPIProcessLoopback:
    """WASAPIを使用したプロセス別ループバック録音"""

    def __init__(self, process_id: Optional[int] = None):
        """
        初期化
        Args:
            process_id: キャプチャするプロセスID（Noneの場合はシステム全体）
        """
        if not WASAPI_AVAILABLE:
            raise ImportError("comtypes/pycawが必要です")

        self.process_id = process_id
        self.audio_client: Optional[IAudioClient] = None
        self.capture_client: Optional[IAudioCaptureClient] = None
        self.waveformat: Optional[WAVEFORMATEX] = None
        self.is_capturing = False
        self.activation_handler: Optional[AudioInterfaceActivationHandler] = None

    def _initialize_with_process_loopback(self) -> bool:
        """
        プロセス別ループバックでWASAPIを初期化（Windows 10 20H1+）
        Returns:
            bool: 初期化に成功した場合True
        """
        try:
            import ctypes
            from ctypes import windll

            # ActivateAudioInterfaceAsync APIをロード
            try:
                mmdevapi = windll.mmdevapi
                ActivateAudioInterfaceAsync = mmdevapi.ActivateAudioInterfaceAsync
            except Exception as e:
                logger.error(f"ActivateAudioInterfaceAsync API読み込みエラー: {e}")
                return False

            # デバイスIDを構築
            # DEVINTERFACE_AUDIO_RENDER = "{E6327CAD-DCEC-4949-AE8A-991E976A79D2}"
            device_id = f"{{0.0.1.00000000}}.{{E6327CAD-DCEC-4949-AE8A-991E976A79D2}}"

            # アクティベーションパラメータを設定
            activation_params = AUDIOCLIENT_ACTIVATION_PARAMS()
            activation_params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
            activation_params.ProcessLoopbackParams.TargetProcessId = self.process_id
            activation_params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE

            # コールバックハンドラーを作成
            self.activation_handler = AudioInterfaceActivationHandler()

            # ActivateAudioInterfaceAsyncを呼び出し
            operation_ptr = POINTER(IActivateAudioInterfaceAsyncOperation)()

            # PropVariantを使用してパラメータを渡す必要があるが、
            # comtypesでの実装が複雑なため、Noneを渡す
            # 実際にはPROPVARIANT構造体にactivation_paramsを設定する必要がある
            logger.warning("ActivateAudioInterfaceAsync実装は複雑なため、")
            logger.warning("プロセス別ループバックは現在サポートされていません")
            logger.warning("システム全体の音声録音にフォールバックします")

            return False

        except Exception as e:
            logger.error(f"プロセスループバック初期化エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def initialize(self) -> bool:
        """
        WASAPIオーディオキャプチャを初期化
        Returns:
            bool: 初期化に成功した場合True
        """
        try:
            # COMの初期化
            comtypes.CoInitialize()

            # プロセスIDが指定されている場合、プロセス別ループバックを試みる
            if self.process_id:
                logger.info(f"プロセスID {self.process_id} でプロセス別ループバックを試みます")
                if self._initialize_with_process_loopback():
                    return True
                logger.warning("プロセス別ループバックに失敗。システム全体の録音にフォールバックします")

            # デフォルトのオーディオレンダリングデバイスを取得
            device_enumerator = comtypes.CoCreateInstance(
                CLSID_MMDeviceEnumerator,
                IMMDeviceEnumerator,
                CLSCTX_ALL
            )

            # デフォルトのレンダリングデバイスを取得（eRender = 0, eConsole = 0）
            default_device = POINTER(IMMDevice)()
            hr = device_enumerator.GetDefaultAudioEndpoint(0, 0, comtypes.byref(default_device))

            if hr != 0:
                logger.error(f"デフォルトデバイス取得エラー: {hr}")
                return False

            # IAudioClientを取得
            audio_client_ptr = POINTER(IUnknown)()
            hr = default_device.Activate(
                comtypes.byref(IID_IAudioClient),
                CLSCTX_ALL,
                None,
                comtypes.byref(audio_client_ptr)
            )

            if hr != 0:
                logger.error(f"IAudioClient取得エラー: {hr}")
                return False

            self.audio_client = cast(audio_client_ptr, POINTER(IAudioClient))

            # ミックスフォーマットを取得
            pwfx = POINTER(WAVEFORMATEX)()
            self.audio_client.GetMixFormat(comtypes.byref(pwfx))
            self.waveformat = pwfx.contents

            logger.info(f"オーディオフォーマット: {self.waveformat.nChannels}ch, "
                       f"{self.waveformat.nSamplesPerSec}Hz, "
                       f"{self.waveformat.wBitsPerSample}bit")

            # オーディオクライアントを初期化（ループバックモード）
            # 注: プロセス別キャプチャにはActivateAudioInterfaceAsyncが必要
            hns_requested_duration = REFTIMES_PER_SEC  # 1秒

            # ループバックモードでは自動変換とSRC品質フラグも追加
            stream_flags = (AUDCLNT_STREAMFLAGS_LOOPBACK |
                          AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
                          AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)

            hr = self.audio_client.Initialize(
                AUDCLNT_SHAREMODE_SHARED,
                stream_flags,
                hns_requested_duration,
                0,
                pwfx,
                None
            )

            if hr != 0:
                logger.error(f"IAudioClient初期化エラー: {hr}")
                return False

            # IAudioCaptureClientを取得
            capture_client_ptr = POINTER(IUnknown)()
            hr = self.audio_client.GetService(
                comtypes.byref(IID_IAudioCaptureClient),
                comtypes.byref(capture_client_ptr)
            )

            if hr != 0:
                logger.error(f"IAudioCaptureClient取得エラー: {hr}")
                return False

            self.capture_client = cast(capture_client_ptr, POINTER(IAudioCaptureClient))

            logger.info("WASAPI初期化成功")
            return True

        except Exception as e:
            logger.error(f"WASAPI初期化エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def start_capture(self) -> bool:
        """
        キャプチャを開始
        Returns:
            bool: 開始に成功した場合True
        """
        if not self.audio_client:
            logger.error("オーディオクライアントが初期化されていません")
            return False

        try:
            hr = self.audio_client.Start()
            if hr != 0:
                logger.error(f"キャプチャ開始エラー: {hr}")
                return False

            self.is_capturing = True
            logger.info("キャプチャ開始")
            return True

        except Exception as e:
            logger.error(f"キャプチャ開始エラー: {e}")
            return False

    def read_data(self) -> Optional[bytes]:
        """
        オーディオデータを読み取り
        Returns:
            Optional[bytes]: 読み取ったオーディオデータ（バイト列）
        """
        if not self.capture_client or not self.is_capturing:
            return None

        try:
            # 次のパケットサイズを取得
            packet_length = comtypes.c_uint32()
            hr = self.capture_client.GetNextPacketSize(comtypes.byref(packet_length))

            if hr != 0:
                # AUDCLNT_E_DEVICE_INVALIDATED = 0x88890004 = -2004287481
                if hr == -2004287481:
                    logger.error("オーディオデバイスが無効化されました")
                    self.is_capturing = False
                return None

            if packet_length.value == 0:
                return None

            # バッファを取得
            data_ptr = POINTER(comtypes.c_byte)()
            num_frames_to_read = comtypes.c_uint32()
            flags = comtypes.c_uint32()
            device_position = comtypes.c_uint64()
            qpc_position = comtypes.c_uint64()

            hr = self.capture_client.GetBuffer(
                comtypes.byref(data_ptr),
                comtypes.byref(num_frames_to_read),
                comtypes.byref(flags),
                comtypes.byref(device_position),
                comtypes.byref(qpc_position)
            )

            if hr != 0:
                if hr == -2004287481:
                    logger.error("オーディオデバイスが無効化されました")
                    self.is_capturing = False
                return None

            # データをコピー
            num_frames = num_frames_to_read.value
            if num_frames > 0:
                frame_size = self.waveformat.nBlockAlign
                data_size = num_frames * frame_size

                # ctypes.string_at を使用してバイト列を取得
                import ctypes
                data = ctypes.string_at(data_ptr, data_size)

                # バッファを解放
                self.capture_client.ReleaseBuffer(num_frames)

                return data
            else:
                # フレーム数が0の場合もバッファを解放
                self.capture_client.ReleaseBuffer(0)

            return None

        except Exception as e:
            logger.warning(f"データ読み取りエラー: {e}")
            return None

    def stop_capture(self) -> bool:
        """
        キャプチャを停止
        Returns:
            bool: 停止に成功した場合True
        """
        if not self.audio_client:
            return False

        try:
            hr = self.audio_client.Stop()
            if hr != 0:
                logger.error(f"キャプチャ停止エラー: {hr}")
                return False

            self.is_capturing = False
            logger.info("キャプチャ停止")
            return True

        except Exception as e:
            logger.error(f"キャプチャ停止エラー: {e}")
            return False

    def cleanup(self):
        """リソースをクリーンアップ"""
        try:
            if self.is_capturing:
                self.stop_capture()

            self.capture_client = None
            self.audio_client = None
            comtypes.CoUninitialize()

        except Exception as e:
            logger.error(f"クリーンアップエラー: {e}")

    def get_format_info(self):
        """
        オーディオフォーマット情報を取得
        Returns:
            dict: フォーマット情報
        """
        if not self.waveformat:
            return None

        return {
            'channels': self.waveformat.nChannels,
            'sample_rate': self.waveformat.nSamplesPerSec,
            'bits_per_sample': self.waveformat.wBitsPerSample,
            'block_align': self.waveformat.nBlockAlign,
        }
