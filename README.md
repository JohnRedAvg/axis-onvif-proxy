# Axis ONVIF Proxy for Frigate

A lightweight Python/Flask proxy that acts as a "man-in-the-middle" between Frigate and older Axis cameras (like the Q6128-E) to fix ONVIF auto-tracking issues.

## The Problem
Axis cameras often fail to report `MoveStatus` capabilities correctly via ONVIF, causing Frigate's auto-tracking to fail or throw errors. Frigate developers adhere strictly to the ONVIF spec, so camera-specific quirks are not patched upstream.

## The Solution
This proxy:
1.  Forwards SOAP requests from Frigate to the Axis camera.
2.  Intercepts the XML responses.
3.  Injects `MoveStatus="true"` into capability responses.
4.  Injects dummy `IDLE` status into `GetStatus` responses.
5.  Passes RTSP streams directly (media bypasses the proxy).

## Usage

### 1. Configure
Edit `docker-compose.yml` to set your camera details:

```yaml
    environment:
      - CAMERA_IP=192.168.1.50   # Your Axis Camera IP
      - CAMERA_USER=root        # Your Axis username
      - CAMERA_PASS=password    # Your Axis password
```

### 2. Run
```bash
docker-compose up -d --build
```
The proxy will listen on port `8080`.

### 3. Update Frigate Config
In your `frigate.yml`:

```yaml
cameras:
  your_axis_camera:
    ffmpeg:
      inputs:
        # Keep the RTSP URL pointing DIRECTLY to the camera (port 554)
        - path: rtsp://root:password@192.168.1.50:554/axis-media/media.amp
          roles:
            - detect
            - record
    onvif:
      # Point ONVIF to this PROXY (port 8080)
      host: 192.168.1.X  # IP of the machine running this proxy
      port: 8080
      user: root         # These credentials are used by Frigate to talk to the proxy
      password: password # (The proxy handles auth to the real camera)
```

## Troubleshooting
Check logs:
```bash
docker-compose logs -f
```
