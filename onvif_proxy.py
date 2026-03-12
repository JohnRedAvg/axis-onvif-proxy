from flask import Flask, request, Response
import requests
import re
import os
import sys

app = Flask(__name__)

# --- CONFIGURATION ---
# Read from Environment Variables or Default
CAMERA_IP = os.getenv("CAMERA_IP", "192.168.1.50")
CAMERA_PORT = int(os.getenv("CAMERA_PORT", "80"))
CAMERA_USER = os.getenv("CAMERA_USER", "root")
CAMERA_PASS = os.getenv("CAMERA_PASS", "password")

if CAMERA_IP == "192.168.1.50" and CAMERA_PASS == "password":
    print("WARNING: Using default credentials. Set CAMERA_IP, CAMERA_USER, and CAMERA_PASS environment variables.")

# ---------------------
TARGET_URL = f"http://{CAMERA_IP}:{CAMERA_PORT}"
AXIS_MAX_ZOOM = 0.545454  # Default fallback max zoom limit for Axis cameras. Will be updated dynamically.

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def onvif_proxy(path):
    global AXIS_MAX_ZOOM
    # 1. Forward Frigate's incoming request to the real camera
    # Handle root path correctly if path is empty
    if not path:
        camera_url = TARGET_URL
    else:
        camera_url = f"{TARGET_URL}/{path}"
        
    # Strip the 'Host' header so the requests library sets it correctly for the camera
    headers = {key: value for (key, value) in request.headers if key.lower() != 'host'}
    
    # NEW: Intercept AbsoluteMove requests from Frigate to clamp zoom.
    # Frigate has a bug where it requests zoom=1.0 during calibration regardless of the camera's actual max limit.
    request_data = request.get_data()
    if b'AbsoluteMove' in request_data:
        request_text = request_data.decode('utf-8', errors='ignore')
        # We find <*Position> ... <*Zoom x="VALUE" ... />
        match = re.search(r'(<[^:]*:?Position>.*?<[^:]*:?Zoom[^>]*x=")([\d\.]+)(")', request_text, re.DOTALL)
        if match:
            requested_zoom = float(match.group(2))
            if requested_zoom > AXIS_MAX_ZOOM:
                request_text = request_text[:match.start(2)] + str(AXIS_MAX_ZOOM) + request_text[match.end(2):]
                request_data = request_text.encode('utf-8')
                if 'Content-Length' in headers:
                    headers['Content-Length'] = str(len(request_data))

    try:
        # We use HTTPDigestAuth as Axis usually requires Digest authentication for ONVIF
        cam_response = requests.request(
            method=request.method,
            url=camera_url,
            headers=headers,
            data=request_data,
            auth=requests.auth.HTTPDigestAuth(CAMERA_USER, CAMERA_PASS),
            timeout=5
        )
    except requests.exceptions.RequestException as e:
        return Response(f"Proxy error connecting to camera: {e}", status=502)
    
    content = cam_response.text
    
    # 2. Intercept and Modify: Capabilities
    # When Frigate asks what the camera can do, we inject 'MoveStatus="true"'
    # into the PTZ capabilities XML tag.
    if "GetNodesResponse" in content or "GetServiceCapabilitiesResponse" in content:
        if "MoveStatus" not in content:
            # Uses regex to find the capabilities tag and insert the MoveStatus flag
            # Note: tptz might have a namespace prefix or not, depending on camera
            content = re.sub(
                r'(<(?:tptz:|tt:)?Capabilities[^>]*)>', 
                r'\1 MoveStatus="true">', 
                content
            )
            
    # 3. Intercept and Modify: PTZ Status
    # When Frigate asks if the camera is currently moving, we inject a dummy 'IDLE'
    # response so Frigate doesn't throw a parsing error.
    if "GetStatusResponse" in content:
        if "MoveStatus" not in content:
            # We inject the fake MoveStatus right before the closing PTZStatus tag
            # We need to match the namespace used in the response (usually tptz)
            # Find the closing tag to guess the namespace prefix? Or just assume tptz/tt based on response?
            
            # Simple heuristic: Check if tptz:PTZStatus exists, otherwise try tt:PTZStatus or just PTZStatus
            
            # Default to tptz as per example, but maybe generic regex is safer?
            # The example used hardcoded tptz. Let's try to be smart or stick to example.
            
            fake_move_status = """
            <tptz:MoveStatus>
                <tptz:PanTilt>IDLE</tptz:PanTilt>
                <tptz:Zoom>IDLE</tptz:Zoom>
            </tptz:MoveStatus>
            """
            
            if '</tptz:PTZStatus>' in content:
                 content = content.replace('</tptz:PTZStatus>', f'{fake_move_status}</tptz:PTZStatus>')
            elif '</tt:PTZStatus>' in content:
                 # Adjust namespace if needed
                 fake_move_status_tt = fake_move_status.replace('tptz:', 'tt:')
                 content = content.replace('</tt:PTZStatus>', f'{fake_move_status_tt}</tt:PTZStatus>')

    # 4. Return the spoofed XML back to Frigate
    
    # NEW: Parse the camera's max zoom limit from profile configurations to robustly cap Zoom requests later.
    if "GetProfilesResponse" in content or "GetNodesResponse" in content:
        zoom_limits_match = re.search(r'<[^:]*:?ZoomLimits>.*?<[^:]*:?Max>([\d\.]+)</[^:]*:?Max>', content, re.DOTALL)
        if zoom_limits_match:
            AXIS_MAX_ZOOM = float(zoom_limits_match.group(1))

    # NEW: Rewrite the camera's IP/port to the proxy's Host so Frigate doesn't bypass the proxy.
    # request.host contains the IP/port Frigate used to connect to the proxy (e.g. "192.168.1.36:8180")
    # request.host is robust but sometimes XAddr uses http://IP/ or http://IP:PORT/
    # We will use regex to safely replace the exact camera IP and port with the proxy host.
    content = re.sub(
        r'http://' + re.escape(CAMERA_IP) + r'(?::' + re.escape(str(CAMERA_PORT)) + r')?([^a-zA-Z0-9.:])',
        r'http://' + request.host + r'\1',
        content
    )

    # We pass along the original status code and headers, but with our modified body
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    proxy_headers = [
        (name, value) for (name, value) in cam_response.headers.items()
        if name.lower() not in excluded_headers
    ]
    
    return Response(content, cam_response.status_code, proxy_headers)

if __name__ == '__main__':
    # Run the proxy on port 8080 (Listen on all interfaces)
    print(f"Starting Axis ONVIF Proxy for {TARGET_URL} on port 8080...")
    app.run(host='0.0.0.0', port=8080)
