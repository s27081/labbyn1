import pytest
import base64
from pytest_html import extras


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call":
        report.extras = getattr(report, "extras", [])
        screenshots = getattr(item, "screenshots", [])
        for screenshot in screenshots:
            if isinstance(screenshot, bytes):
                b64_screenshot = base64.b64encode(screenshot).decode("utf-8")
                report.extras.append(extras.png(b64_screenshot))
            else:
                report.extras.append(extras.png(screenshot))
