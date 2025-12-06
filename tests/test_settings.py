"""
Pytest integration tests for the Settings page and related static assets.
"""

from typing import Generator

import pytest
from app import create_app

@pytest.fixture()
def client() -> Generator:
    """
    Create Flask test client with DEBUG enabled.
    
    :return: A test client instance for making requests
    :rtype: Generator[Any, None, None]
    """
    app = create_app({"DEBUG": True})
    with app.test_client() as client:
        yield client

def test_settings_returns_ok_and_content(client) -> None:
    """
    Ensure the settings route returns HTTP 200 and expected page content.
    """
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Borealis | Settings" in body
    # Ensure tab container and tabs exist
    assert 'class="settings-container"' in body
    assert ">General<" in body
    assert ">Jellyfin<" in body
    assert ">About<" in body

def test_navbar_has_active_settings(client) -> None:
    """
    Ensure navbar is present and Settings tab is marked active.
    """
    resp = client.get("/settings")
    body = resp.get_data(as_text=True)
    # Navbar elements
    assert '<header class="navbar"' in body
    assert ">Home<" in body
    assert ">Users<" in body
    assert ">Libraries<" in body
    assert ">Settings<" in body
    # Active state on Settings for settings route
    assert '<a href="/settings" class="active">Settings</a>' in body

def test_settings_tabs_have_roles_and_aria(client) -> None:
    """
    Validate ARIA roles for tabs and tabpanels in the Settings page.
    """
    resp = client.get("/settings")
    body = resp.get_data(as_text=True)

    # Tablist container
    assert 'role="tablist"' in body
    assert 'aria-orientation="vertical"' in body

    # Individual tabs have role="tab" and aria-selected
    assert 'class="settings-tab active" role="tab" aria-selected="true"' in body
    assert 'class="settings-tab" role="tab" aria-selected="false"' in body

    # Tab panels have role="tabpanel" and ids
    assert 'role="tabpanel" id="general"' in body
    assert 'role="tabpanel" id="jellyfin"' in body
    assert 'role="tabpanel" id="about"' in body

    # Initial visibility: only general visible; others hidden
    assert 'id="general"' in body and 'hidden' not in body.split('id="general"')[1][:100]
    assert 'id="jellyfin"' in body and 'hidden' in body.split('id="jellyfin"')[1][:100]
    assert 'id="about"' in body and 'hidden' in body.split('id="about"')[1][:100]

def test_settings_js_link_and_asset_served(client) -> None:
    """
    Ensure settings.js is linked from the template and served as a static asset.
    """
    # Linked script tag present in template
    resp = client.get("/settings")
    body = resp.get_data(as_text=True)
    assert '<script src="../assets/js/settings.js"></script>' in body

    # Static asset served
    js_resp = client.get("/assets/js/settings.js")
    assert js_resp.status_code == 200
    js_text = js_resp.get_data(as_text=True)
    assert "document.querySelectorAll('.settings-tab')" in js_text
    assert "window.addEventListener('hashchange', fromHash)" in js_text

def test_settings_autosave_ui_elements(client) -> None:
    """
    Validate presence of autosave-related UI parts and field IDs used by settings.js.
    """
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert 'id="toast-container"' in body
    assert 'class="toast-container"' in body
    assert 'aria-live="polite"' in body
    assert 'aria-atomic="true"' in body

    assert 'id="hour-format"' in body
    assert 'id="language"' in body
    assert 'id="jf-host"' in body
    assert 'id="jf-port"' in body
    assert 'id="jf-api-key"' in body

    assert "Save</button>" not in body