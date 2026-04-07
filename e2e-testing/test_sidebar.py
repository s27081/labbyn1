import time
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "http://127.0.0.1:3000"

@pytest.fixture(scope="session")
def driver():
    web_options = Options()
    web_options.add_argument("--kiosk")

    # Modern headless mode is much more stable in CI
    web_options.add_argument("--headless=new")
    web_options.add_argument("--no-sandbox")
    web_options.add_argument("--disable-dev-shm-usage")
    web_options.add_argument("--disable-gpu")
    
    # CRITICAL: Force Chrome to bypass CI proxies for local addresses
    web_options.add_argument("--proxy-server='direct://'")
    web_options.add_argument("--proxy-bypass-list=*")
    
    driver = webdriver.Chrome(options=web_options)
    driver.get(BASE_URL)

    yield driver
    driver.quit()

#test
def get_element(driver, element_name):
    return driver.find_elements(By.CSS_SELECTOR, element_name)


def login(driver, username="Service", password="Service", timeout=10):
    wait = WebDriverWait(driver, timeout)
    username_input = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, 'input[placeholder="Enter your name"]')
        )
    )
    password_input = wait.until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[name="password"]'))
    )
    login_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-slot="button"]'))
    )

    username_input.clear()
    username_input.send_keys(username)
    password_input.clear()
    password_input.send_keys(password)
    login_button.click()
    wait.until(EC.url_changes(driver.current_url))


def get_sidebar_elements(driver):
    return driver.find_elements(
        By.XPATH,
        '//div[@data-slot="sidebar-group-label" and normalize-space()="Overview"]'
        '/ancestor::*[@data-slot="sidebar-group"]'
        '//*[@data-slot="sidebar-menu-button"]',
    )


def test_sidebar_navigation(driver, request):
    login(driver)
    items = get_sidebar_elements(driver)
    request.node.screenshots = []
    for index, item in enumerate(items):
        item.click()
        time.sleep(1)

        screenshot = driver.get_screenshot_as_png()
        request.node.screenshots.append(screenshot)
