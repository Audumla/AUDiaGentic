"""Isolated browser checks; never attach to the provider's CDP connection."""
import json
import base64

import pytest

from audiagentic.components.agents.gateway.service.dashboard import render_dashboard_html
from audiagentic.components.agents.gateway.service.dashboard_images import save_image, image_path


def test_dashboard_actions_activity_and_card_icons(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    stamp = "2026-09-05T04:30:00Z"
    projects = []
    for index, name in enumerate(["AUDiaGentic", "BigCherry"]):
        session = {"session-id": f"ses_{index}abc1234567890", "state": "active", "turn-count": 2, "execution-profile-id": "gpt-dev", "provider-id": "gpt-auto", "model-id": "chatgpt", "provider-chat-title": "Review gateway dashboard layout"}
        requests = [{"request-id": f"req_{index}{state}123456789", "session-id": session["session-id"], "state": state, "updated-at": stamp, "activity-type": "tool-progress", "activity-sequence": 13, "focus-tab-available": True} for state in ["running", "completed"]]
        projects.append({"name": name, "project-id": str(index)*64, "sessions": [session], "requests": requests, "queues": {}})
    snapshot = {"projects": projects, "counts": {"running": 2}, "dashboard": {"recent-window-seconds": 43200}}
    with playwright.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except playwright.Error as error:
            pytest.skip(f"headless Chromium unavailable: {error}")
        try:
            page = browser.new_page(viewport={"width": 1680, "height": 1050}, locale="en-AU", timezone_id="Australia/Sydney")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            def respond(route):
                if "/project-image" in route.request.url:
                    if route.request.method == "POST":
                        body = route.request.post_data_json
                        save_image(tmp_path, body["project-id"], body["png"])
                        projects[0]["image-version"] = "1"
                        route.fulfill(content_type="application/json", body='{"ok":true}')
                    else:
                        route.fulfill(content_type="image/png", body=image_path(tmp_path, projects[0]["project-id"]).read_bytes())
                elif "/snapshot" in route.request.url:
                    route.fulfill(content_type="application/json", body=json.dumps(snapshot))
                else:
                    route.fulfill(content_type="text/html", body=render_dashboard_html("/dashboard/snapshot").decode())
            page.route("http://dashboard.test/**", respond)
            page.goto("http://dashboard.test/dashboard")
            page.locator(".request-row").first.wait_for()
            assert page.locator('.request-header').count() == 0
            backgrounds = []
            for theme in ['default', 'dark', 'mid', 'light']:
                page.locator('#theme-filter').select_option(theme)
                assert page.locator('html').get_attribute('data-theme') == theme
                backgrounds.append(page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor'))
                page.screenshot(path=str(tmp_path / f'theme-{theme}.png'), full_page=True)
            assert len(set(backgrounds)) == 4
            page.reload()
            page.locator('.request-row').first.wait_for()
            assert page.locator('#theme-filter').input_value() == 'light'
            page.evaluate('s=>draw(s)', snapshot)
            assert page.locator('html').get_attribute('data-theme') == 'light'
            page.locator('#theme-filter').select_option('default')
            assert page.locator("#counts .summary-icon").count() == 6
            assert page.locator(".project-avatar").count() == 2
            assert page.locator('.project-avatar').first.evaluate('e=>getComputedStyle(e).caretColor') == 'rgba(0, 0, 0, 0)'
            assert page.locator('#recent-window').evaluate('e=>getComputedStyle(e).caretColor') != 'rgba(0, 0, 0, 0)'
            assert page.locator(".request-row:has(.badge.state-completed) .activity-badge").first.inner_text() == "Activity Count #13"
            assert page.locator(".request-row:has(.badge.state-completed) .cancel-request").count() == 0
            assert page.locator('.session').count() == 2
            assert page.locator(".work-section-active .cancel-request").count() == 2
            row = page.locator(".request-row").first
            assert row.locator(".request-actions .focus-chat").count() == 1
            assert row.locator(".focus-chat").bounding_box()["x"] > row.locator(".request-updated").bounding_box()["x"]
            assert page.locator(".project").first.evaluate("e=>getComputedStyle(e).borderTopWidth") == "0px"
            png = page.evaluate("""()=>{const c=document.createElement('canvas');c.width=c.height=64;const x=c.getContext('2d');x.fillStyle='#a58bff';x.fillRect(8,8,48,48);return c.toDataURL('image/png').split(',')[1]}""")
            with page.expect_file_chooser() as chooser:
                page.locator(".project-avatar").first.click()
            chooser.value.set_files({"name": "project.png", "mimeType": "image/png", "buffer": base64.b64decode(png)})
            page.locator(".project-avatar img").wait_for()
            assert image_path(tmp_path, projects[0]["project-id"]).is_file()
            assert page.locator(".project-avatar img").evaluate("e=>e.complete&&e.naturalWidth===128")
            assert not errors
            header = page.locator('.work-section-head').first.bounding_box()
            panel = page.locator('.session').first.bounding_box()
            assert header['width'] >= panel['width']
            assert page.locator('.session-actions').first.inner_text().endswith('2 Requests')
            assert page.locator('#show-closed, #show-empty').count() == 0
            page.locator('#layout-filter').select_option('rows')
            assert page.locator('.project-head').count() == 0
            assert page.locator('.row-session-list').count() == 1
            assert page.locator('.session-identity .project-avatar').count() == 2
            assert page.locator('.work-section-active').count() == 1
            varied = json.loads(json.dumps(snapshot))
            varied['projects'][1]['sessions'][0]['turn-count'] = 12345
            varied['projects'][1]['sessions'][0]['pending-turns'] = 12
            page.evaluate('s=>draw(s)', varied)
            centers = page.locator('.session-actions > .badge').evaluate_all('els=>els.map(e=>{const r=e.getBoundingClientRect();return r.x+r.width/2})')
            assert max(centers) - min(centers) < 1
            assert page.locator('.request-row').last.evaluate("e=>getComputedStyle(e,'::before').content") == '"└─"'
            assert '│' in page.locator('.request-row').first.evaluate("e=>getComputedStyle(e,'::after').content")
            page.locator('#layout-filter').select_option('columns')
            heights = page.locator('.request-row').first.evaluate("e=>[...e.querySelectorAll('.badge,.activity-badge')].map(x=>x.getBoundingClientRect().height)")
            assert len(set(heights)) == 1
            screenshot = tmp_path / "dashboard.png"
            page.screenshot(path=str(screenshot), full_page=True)
            print(f"Dashboard screenshot: {screenshot}")
            # No automatic toggle event may turn a default into a user choice.
            old_snapshot = json.loads(json.dumps(snapshot))
            for project in old_snapshot['projects']:
                project['sessions'][0]['state'] = 'closed'
                for request in project['requests']:
                    request['state'] = 'failed'
                    request['updated-at'] = '2020-01-01T00:00:00Z'
                    request['error'] = {'code': 'EXT-TEST-001', 'message': 'Full diagnostic ' * 40}
            page.evaluate('s=>draw(s)', old_snapshot)
            assert page.locator('.work-section-closed .section-toggle').first.get_attribute('aria-expanded') == 'false'
            page.locator('.work-section-closed .section-toggle').first.click()
            assert not page.locator('.session').first.evaluate('e=>e.open')
            page.locator('.session > summary').first.click()
            page.evaluate('s=>draw(s)', old_snapshot)
            assert page.locator('.session').first.evaluate('e=>e.open')
            diagnostic = page.locator('.request-diagnostic').first
            assert 'Full diagnostic' in diagnostic.get_attribute('title')
            page.reload()
            page.locator('.session').first.wait_for()
            page.evaluate('s=>draw(s)', old_snapshot)
            assert page.locator('.session').first.evaluate('e=>e.open')
            page.locator('.session > summary').first.click()
            page.evaluate('s=>draw(s)', old_snapshot)
            assert not page.locator('.session').first.evaluate('e=>e.open')
            page.locator('#collapse-hours').fill('0')
            page.locator('#collapse-hours').dispatch_event('change')
            assert page.evaluate("localStorage.getItem('gateway-dashboard-collapse-hours')") == '0'
            # Explicitly collapsed first session stays closed; untouched one opens.
            assert not page.locator('.session').first.evaluate('e=>e.open')
            assert page.locator('.session').last.evaluate('e=>e.open')
            grouped_snapshot = json.loads(json.dumps(old_snapshot))
            project = grouped_snapshot['projects'][0]
            base = project['sessions'][0]
            base['state'] = 'closed'
            for state in ['expired', 'active']:
                session = dict(base, **{'session-id': 'ses_'+state, 'state': state})
                project['sessions'].append(session)
                project['requests'].append(dict(project['requests'][0], **{'session-id': session['session-id'], 'request-id': 'req_'+state}))
            snapshot.clear()
            snapshot.update(grouped_snapshot)
            page.evaluate('s=>draw(s)', grouped_snapshot)
            first_project = page.locator('.project').first
            assert first_project.locator('.work-section-head h3').all_text_contents() == ['Active', 'Closed', 'Expired']
            assert first_project.locator('.session').count() == 3
            assert first_project.locator('.work-section-failed').count() == 0
            expired = first_project.locator('.work-section-expired')
            assert expired.locator('.section-toggle').get_attribute('aria-expanded') == 'false'
            expired.locator('.section-toggle').click()
            assert not errors, errors
            page.evaluate('s=>draw(s)', grouped_snapshot)
            assert expired.locator('.section-toggle').get_attribute('aria-expanded') == 'true'
            active = first_project.locator('.work-section-active .section-toggle')
            assert active.get_attribute('aria-expanded') == 'true'
            active.click()
            page.evaluate('s=>draw(s)', grouped_snapshot)
            assert active.get_attribute('aria-expanded') == 'false'
            page.reload()
            page.locator('.section-toggle').first.wait_for()
            assert first_project.locator('.work-section-active .section-toggle').get_attribute('aria-expanded') == 'false'
            assert first_project.locator('.session').count() == 3
            assert first_project.locator('.work-section-closed .badge.state-failed').count() == 2
        finally:
            browser.close()
