import adsk.core
import adsk.fusion


def test_fusion_api_is_available() -> None:
    assert adsk.core.Application
    assert adsk.fusion.Design
