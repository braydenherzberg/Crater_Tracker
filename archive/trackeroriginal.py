import cv2
import numpy as np
import sys

def tuner_dashboard(video_path):
    print(f"Loading video: {video_path}...")
    
    # 1. LOAD VIDEO
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    
    total_frames = len(frames)
    if total_frames == 0:
        print("Error: No frames loaded.")
        return
        
    print(f"Loaded {total_frames} frames.")
    print("CONTROLS: Independent Left/Right Zones + Full Visualization.")

    # --- HARDCODED MARGINS ---
    L_MARGIN = 100
    R_MARGIN = 100
    T_MARGIN = 50
    # -------------------------

    window_name = 'Crater Analysis Dashboard'
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1200, 800)

    def nothing(x):
        pass

    h_init, w_init, _ = frames[0].shape

    # 3. CREATE SLIDERS (Updated Labels)
    cv2.createTrackbar('FRAME', window_name, 0, total_frames - 1, nothing)
    cv2.createTrackbar('THRESHOLD', window_name, 94, 255, nothing)
    cv2.createTrackbar('SMOOTHING', window_name, 15, 100, nothing)
    cv2.createTrackbar('DESPECKLE', window_name, 6, 50, nothing)
    
    # INDEPENDENT ZONES (Updated Labels)
    cv2.createTrackbar('CRATER LEFT BOUND', window_name, 150, w_init // 2, nothing)
    cv2.createTrackbar('CRATER RIGHT BOUND', window_name, 150, w_init // 2, nothing)
    
    # FLOOR Y (Updated Label)
    cv2.createTrackbar('SURFACE BOUNDARY', window_name, h_init // 2, h_init, nothing)
    
    scan_mode = 1 # Start Bottom-Up

    while True:
        try:
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
        except:
            break

        # --- GET SLIDER VALUES (Updated Keys) ---
        frame_idx = cv2.getTrackbarPos('FRAME', window_name)
        thresh_val = cv2.getTrackbarPos('THRESHOLD', window_name)
        smooth_val = cv2.getTrackbarPos('SMOOTHING', window_name)
        despeckle_val = cv2.getTrackbarPos('DESPECKLE', window_name)
        
        zone_l = cv2.getTrackbarPos('CRATER LEFT BOUND', window_name)
        zone_r = cv2.getTrackbarPos('CRATER RIGHT BOUND', window_name)
        floor_y = cv2.getTrackbarPos('SURFACE BOUNDARY', window_name)

        if smooth_val < 1: smooth_val = 1
        if despeckle_val > 0 and despeckle_val % 2 == 0: despeckle_val += 1

        current_frame = frames[frame_idx].copy()
        h, w, _ = current_frame.shape
        center_x = w // 2

        bracket_left_x = center_x - zone_l
        bracket_right_x = center_x + zone_r

        # --- ANALYSIS ---
        gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (15, 15), 0)
        _, thresh = cv2.threshold(blurred, thresh_val, 255, cv2.THRESH_BINARY_INV)
        
        solid_mask = np.zeros_like(thresh)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            cv2.drawContours(solid_mask, [largest_contour], -1, (255), thickness=cv2.FILLED)

        # 4. Scan
        raw_points_x = []
        raw_points_y = []

        if L_MARGIN + R_MARGIN < w:
            for x in range(L_MARGIN, w - R_MARGIN, 5):
                
                # Check Zone
                in_zone = (x > bracket_left_x) and (x < bracket_right_x)

                col = solid_mask[:, x]
                found_y = -1
                
                if scan_mode == 1: # BOTTOM-UP
                    col_reversed = col[::-1]
                    air_pixels = np.where(col_reversed == 0)[0]
                    if len(air_pixels) > 0:
                        dist_from_bottom = air_pixels[0]
                        found_y = (h - 1) - dist_from_bottom
                else: # TOP-DOWN
                    sand_pixels = np.where(col == 255)[0]
                    valid_pixels = sand_pixels[sand_pixels > T_MARGIN]
                    if len(valid_pixels) > 0:
                        found_y = valid_pixels[0]

                # --- THE FIX FOR BOTTOM-UP GAPS ---
                # 1. If we found nothing (-1) outside the zone -> Force Floor
                if found_y == -1 and not in_zone:
                    found_y = floor_y
                
                # 2. If we found something BUT it is suspiciously deep (bottom 5px)
                #    and we are outside the zone -> Force Floor
                elif not in_zone and found_y > (h - 5):
                    found_y = floor_y
                # ----------------------------------

                if found_y != -1 and found_y < h - 5:
                    
                    # --- CLAMPING LOGIC ---
                    if not in_zone:
                        # Force point to conform to manual floor limit
                        if found_y > floor_y:
                            found_y = floor_y
                    # ----------------------

                    raw_points_x.append(x)
                    raw_points_y.append(found_y)

        # Despeckle
        if despeckle_val > 1 and len(raw_points_y) > despeckle_val:
            y_array = np.array(raw_points_y)
            despeckled_y = y_array.copy()
            k = despeckle_val // 2
            for i in range(len(y_array)):
                start = max(0, i - k)
                end = min(len(y_array), i + k + 1)
                despeckled_y[i] = np.median(y_array[start:end])
            raw_points_y = despeckled_y.tolist()

        # Smoothing
        final_points = []
        if len(raw_points_y) > smooth_val:
            kernel = np.ones(smooth_val) / smooth_val
            smoothed_y = np.convolve(raw_points_y, kernel, mode='same')
            
            for i in range(len(raw_points_x)):
                if i > smooth_val and i < len(raw_points_x) - smooth_val:
                    final_points.append((raw_points_x[i], int(smoothed_y[i])))

        # --- DRAWING ---
        mask_display = cv2.cvtColor(solid_mask, cv2.COLOR_GRAY2BGR)

        def draw_on_both(pt1, pt2, color, thickness=1):
            cv2.line(current_frame, pt1, pt2, color, thickness)
            cv2.line(mask_display, pt1, pt2, color, thickness)

        # 1. Margins
        cv2.rectangle(current_frame, (L_MARGIN, T_MARGIN), (w-R_MARGIN, h), (255, 0, 0), 1)

        # 2. Zone Brackets
        draw_on_both((bracket_left_x, 0), (bracket_left_x, h), (0, 255, 255), 1)
        draw_on_both((bracket_right_x, 0), (bracket_right_x, h), (0, 255, 255), 1)

        # 3. Manual Floor (SURFACE BOUNDARY)
        draw_on_both((L_MARGIN, floor_y), (w-R_MARGIN, floor_y), (255, 255, 0), 2)
        cv2.putText(current_frame, "SURFACE BOUNDARY", (L_MARGIN + 5, floor_y - 5), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        # 4. Profile
        if len(final_points) > 1:
            pts = np.array(final_points, np.int32).reshape((-1, 1, 2))
            cv2.polylines(current_frame, [pts], isClosed=False, color=(0, 255, 0), thickness=3)
            cv2.polylines(mask_display, [pts], isClosed=False, color=(0, 255, 0), thickness=3)

        # --- TEXT ---
        cv2.putText(current_frame, "CONTROLS:", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
        cv2.putText(current_frame, "Press 'Q' or 'ESC' to Quit", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        mode_text = "SCAN MODE: BOTTOM-UP (Press 'M')" if scan_mode == 1 else "SCAN MODE: TOP-DOWN (Press 'M')"
        color = (0, 255, 255) if scan_mode == 1 else (0, 165, 255)
        cv2.putText(current_frame, mode_text, (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        
        cv2.putText(current_frame, "Use 'SURFACE BOUNDARY' slider to move Cyan Line", (10, 110), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        # Display
        combined = np.vstack((current_frame, mask_display))
        scale = 0.6
        final_view = cv2.resize(combined, (int(combined.shape[1]*scale), int(combined.shape[0]*scale)))
        
        cv2.imshow(window_name, final_view)

        key = cv2.waitKey(10) & 0xFF
        if key == ord('q') or key == 27:
            break
        elif key == ord('m'):
            scan_mode = 1 - scan_mode
            print(f"Switched Mode to: {'Bottom-Up' if scan_mode == 1 else 'Top-Down'}")

    cv2.destroyAllWindows()
    sys.exit()

tuner_dashboard('test.mov')