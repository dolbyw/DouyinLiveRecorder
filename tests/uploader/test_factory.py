from src.models import UploadConfig
from src.uploader import RcloneRcUploadService, RcloneUploadService, create_upload_service


def test_create_upload_service_uses_rc_by_default():
    service = create_upload_service(UploadConfig(enabled=True))

    assert isinstance(service, RcloneRcUploadService)


def test_create_upload_service_can_use_cli_fallback_with_chinese_label():
    service = create_upload_service(UploadConfig(enabled=True, execution_mode="命令行"))

    assert isinstance(service, RcloneUploadService)


def test_create_upload_service_can_use_cli_fallback_with_ascii_label():
    service = create_upload_service(UploadConfig(enabled=True, execution_mode="cli"))

    assert isinstance(service, RcloneUploadService)


def test_create_upload_service_passes_progress_callback_to_rc_service():
    callbacks = []
    callback = callbacks.append

    service = create_upload_service(UploadConfig(enabled=True), progress_callback=callback)

    assert isinstance(service, RcloneRcUploadService)
    assert service.progress_callback is callback
