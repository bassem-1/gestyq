"""Camera selection and capture, by AVCaptureDevice uniqueID (never by position: OpenCV and AVFoundation
enumerate devices differently, and Continuity iPhones come and go).

Pure logic (Device, is_continuity, default_device, choose, status_text) has no AppKit / numpy dependency;
list_devices() and AVCamera import AVFoundation lazily (macOS only)."""
import ctypes
import threading
import time
from dataclasses import dataclass

DISCOVERY_TTL = 3.0           # s a device listing is reused (each discovery logs a system warning)


@dataclass(frozen=True)
class Device:
    uid: str
    name: str
    builtin: bool = False
    continuity: bool = False      # an iPhone / iPad used as a camera


def is_continuity(name, dtype=""):
    n = (name or "").lower()
    return any(k in n for k in ("iphone", "ipad", "continuity"))


def is_builtin(name, dtype=""):
    return "BuiltIn" in (dtype or "") or any(k in (name or "") for k in ("FaceTime", "MacBook", "Built-in"))


def default_device(devs):
    """auto = the built-in camera, else the first that is not an iPhone, else the first."""
    for d in devs:
        if d.builtin:
            return d
    for d in devs:
        if not d.continuity:
            return d
    return devs[0] if devs else None


def choose(devs, cfg):
    """-> (Device | None, note). The saved choice is cfg['camera_id'] (uniqueID); an older file may only
    have camera_name. If the chosen camera is not there (phone away), the default is used for this
    session and `note` says so; the saved choice is never touched."""
    want_id, want_name = cfg.get("camera_id"), cfg.get("camera_name")
    if not want_id and not want_name:
        return default_device(devs), ""
    for d in devs:
        if want_id and d.uid == want_id:
            return d, ""
    if not want_id:
        for d in devs:
            if d.name == want_name:
                return d, ""
    d = default_device(devs)
    label = (want_name or "chosen camera").lower()
    return d, f"{label} not found · using {d.name.lower()}" if d else f"{label} not found"


def status_text(note, device):
    """What the window shows next to the camera list."""
    if note:
        return note
    return device.name.lower() if device else "no camera"


# ------------------------------------------------------------------ AVFoundation
_cache = {"t": -1e9, "devs": []}


def list_devices(force=False):
    """[Device] of every video input right now (cached DISCOVERY_TTL s unless force)."""
    now = time.monotonic()
    if not force and now - _cache["t"] < DISCOVERY_TTL:
        return list(_cache["devs"])
    try:
        import AVFoundation as AV
        types = [getattr(AV, t) for t in ("AVCaptureDeviceTypeBuiltInWideAngleCamera", "AVCaptureDeviceTypeExternal")
                 if hasattr(AV, t)]
        if types:
            ds = AV.AVCaptureDeviceDiscoverySession.discoverySessionWithDeviceTypes_mediaType_position_(
                types, AV.AVMediaTypeVideo, AV.AVCaptureDevicePositionUnspecified).devices()
        else:
            ds = AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo)
        devs = []
        for d in ds:
            name, dtype = str(d.localizedName()), str(d.deviceType()) if hasattr(d, "deviceType") else ""
            devs.append(Device(str(d.uniqueID()), name, is_builtin(name, dtype), is_continuity(name, dtype)))
    except Exception as e:
        print("camera discovery failed:", e)
        devs = []
    _cache.update(t=now, devs=devs)
    return list(devs)


def _queue(label):
    """A serial dispatch queue (libdispatch through ctypes; PyObjC's dispatch module is not installed)."""
    lib = ctypes.CDLL("/usr/lib/system/libdispatch.dylib")
    lib.dispatch_queue_create.restype = ctypes.c_void_p
    lib.dispatch_queue_create.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    import objc
    return objc.objc_object(c_void_p=lib.dispatch_queue_create(label.encode(), None))


def _preset_for(AV, width):
    names = (["AVCaptureSessionPreset1920x1080"] if width >= 1920 else []) + [
        "AVCaptureSessionPreset1280x720", "AVCaptureSessionPresetHigh"]
    return [getattr(AV, n) for n in names if hasattr(AV, n)]


class AVCamera:
    """AVCaptureSession on one device (by uniqueID). Keeps only the newest frame; read() hands it out as a
    BGR numpy array, blocking up to `timeout` s for a frame it has not returned yet."""

    def __init__(self):
        self.session = self.delegate = self.queue = None
        self.cond = threading.Condition()
        self.frame, self.seq, self.last = None, 0, 0
        self.stamp = 0.0                    # time.monotonic() the newest frame reached Python
        self.size = (0, 0)

    def open(self, uid, width=1920):
        import AVFoundation as AV
        import numpy as np
        dev = AV.AVCaptureDevice.deviceWithUniqueID_(uid)
        if dev is None:
            return False
        inp, err = AV.AVCaptureDeviceInput.deviceInputWithDevice_error_(dev, None)
        if inp is None:
            print("camera input failed:", err)
            return False
        out = AV.AVCaptureVideoDataOutput.alloc().init()
        out.setVideoSettings_({"PixelFormatType": 1111970369})          # kCVPixelFormatType_32BGRA
        out.setAlwaysDiscardsLateVideoFrames_(True)
        self.delegate = _make_delegate(self, np)
        self.queue = _queue("gestyq.camera")
        out.setSampleBufferDelegate_queue_(self.delegate, self.queue)
        sess = AV.AVCaptureSession.alloc().init()
        sess.beginConfiguration()
        if not sess.canAddInput_(inp) or not sess.canAddOutput_(out):
            sess.commitConfiguration()
            return False
        sess.addInput_(inp)
        sess.addOutput_(out)
        for preset in _preset_for(AV, width):
            if sess.canSetSessionPreset_(preset):
                sess.setSessionPreset_(preset)
                break
        sess.commitConfiguration()
        sess.startRunning()
        self.session = sess
        ok, _ = self.read(timeout=3.0)
        if not ok:
            self.close()
        return ok

    def _push(self, bgr):
        with self.cond:
            self.frame, self.seq, self.stamp = bgr, self.seq + 1, time.monotonic()
            self.size = (bgr.shape[1], bgr.shape[0])
            self.cond.notify_all()

    def read(self, timeout=1.0):
        with self.cond:
            if self.seq == self.last:
                self.cond.wait(timeout)
            if self.seq == self.last or self.frame is None:
                return False, None
            self.last = self.seq
            return True, self.frame

    def close(self):
        if self.session is not None:
            self.session.stopRunning()      # camera light off
            for o in list(self.session.outputs()):
                o.setSampleBufferDelegate_queue_(None, None)
            self.session = None
        self.delegate = self.queue = self.frame = None


_sink_cls = []


def _make_delegate(cam, np):
    """One FrameSink class per process (an Objective-C class cannot be defined twice); `cam` is set per instance."""
    if not _sink_cls:
        from Foundation import NSObject
        import CoreMedia
        import Quartz

        class FrameSink(NSObject):
            def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sample, conn):
                try:
                    buf = CoreMedia.CMSampleBufferGetImageBuffer(sample)
                    Quartz.CVPixelBufferLockBaseAddress(buf, 1)
                    try:
                        w, h = Quartz.CVPixelBufferGetWidth(buf), Quartz.CVPixelBufferGetHeight(buf)
                        stride = Quartz.CVPixelBufferGetBytesPerRow(buf)
                        base = Quartz.CVPixelBufferGetBaseAddress(buf)
                        raw = np.frombuffer(base.as_buffer(stride * h), np.uint8).reshape(h, stride)
                        bgr = np.ascontiguousarray(raw[:, :w * 4].reshape(h, w, 4)[:, :, :3])
                    finally:
                        Quartz.CVPixelBufferUnlockBaseAddress(buf, 1)
                    self.cam._push(bgr)
                except Exception as e:
                    print("frame error:", e, flush=True)

        _sink_cls.append(FrameSink)
    sink = _sink_cls[0].alloc().init()
    sink.cam = cam
    return sink
