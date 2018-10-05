import cv2
import math
import numpy as np
import logging
from collections import deque

from camcorder.util.defaults import *
from camcorder.util.utilities import extract_metadata
from camcorder.lib.kalman import KalmanFilter

MIN_MOUSE_AREA = 50
MIN_DIST_TO_NODE = 100

THICKNESS_MINOR_CONTOUR = 1
THICKNESS_MAJOR_CONTOUR = 1
DRAW_MINOR_CONTOURS = False
DRAW_MAJOR_CONTOURS = True

TRAIL_LENGTH = 128
DRAW_TRAIL = True
DRAW_KF_TRAIL = True
KF_REGISTRATION_AGE = 10

SEARCH_WINDOW_SIZE = 60

KERNEL_3 = np.ones((3, 3), np.uint8)

nodes = [NODES_A, NODES_B]
leds = [LED_A, LED_B]


def centroid(cnt):
    m = cv2.moments(cnt)
    cx = int(m['m10'] / m['m00'])
    cy = int(m['m01'] / m['m00'])
    return cx, cy


def distance(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


class TrackerResult:
    def __init__(self, t_id, idx, tickstamp=None, led_state=None, last_node=None, node_update=False, fresh=True):
        self.idx = idx
        self.id = t_id
        self.tickstamp = tickstamp
        self.led_state = led_state
        self.last_node = last_node
        self.node_update = node_update
        self.fresh = fresh

class Tracker:
    def __init__(self, idx=0, thresh_mask=100, thresh_detect=35, thresh_led=70):
        super().__init__()
        self.id = idx
        self.n_frames = 0
        self.img = None
        self.thresh_mask = thresh_mask
        self.thresh_detect = 255 - thresh_detect
        self.thresh_led = thresh_led

        self.foi_frame = None
        self.mask_frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), np.uint8)
        self.has_mask = False

        self.nodes = nodes[self.id]
        self.results = deque(maxlen=TRAIL_LENGTH)
        self.last_node = None
        self.active_node = None
        self.node_updated_presented = True

        self.led_pos = leds[self.id]
        self.led_state = False

        self.kf = KalmanFilter()
        self.kf_results = deque(maxlen=TRAIL_LENGTH)
        self.last_kf_pos = (-100, -100)
        self.kf_age = 0

        self._t_track = deque(maxlen=100)
        self.__last_frame_idx = None
        self.__last_frame_tickstamp = None

        self.contours = None
        self.largest_contour = None

        self.search_point = None
        self.search_window_size = SEARCH_WINDOW_SIZE

    def make_mask(self, frame, global_threshold=70):
        logging.debug('Creating mask')
        _, mask = cv2.threshold(frame, global_threshold, 255, cv2.THRESH_BINARY)
        self.mask_frame = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL_3)
        self.has_mask = True

    def get_search_window(self):
        x1 = min(max(0, self.search_point[0] - self.search_window_size // 2), FRAME_WIDTH)
        y1 = min(max(0, self.search_point[1] - self.search_window_size // 2), FRAME_HEIGHT)

        x2 = min(max(0, self.search_point[0] + self.search_window_size // 2), FRAME_WIDTH)
        y2 = min(max(0, self.search_point[1] + self.search_window_size // 2), FRAME_HEIGHT)
        return (x1, y1), (x2, y2)

    def annotate(self):
        # draw search window
        if self.search_point is not None:
            p1, p2 = self.get_search_window()

            cv2.rectangle(self.img, p1, p2, color=(255, 255, 255), thickness=1)
        else:
            cv2.rectangle(self.img, (0, 0), (FRAME_WIDTH-1, FRAME_HEIGHT-1), color=(255, 255, 255), thickness=1)

        # draw all detected contours to see masking issues
        if DRAW_MINOR_CONTOURS and self.contours is not None:
            cv2.drawContours(self.img, self.contours, -1, (150, 150, 0), THICKNESS_MINOR_CONTOUR)

        # draw largest contour and contour label
        if DRAW_MAJOR_CONTOURS and self.largest_contour is not None:
            cv2.drawContours(self.img, [self.largest_contour], 0, (0, 0, 255), THICKNESS_MAJOR_CONTOUR)

        # Marker on centroid of largest contour
        if self.largest_contour is not None:
            cv2.drawMarker(img=self.img, position=centroid(self.largest_contour), color=(0, 255, 0))

        # Label nodes, highlight node closest to largest contour centroid
        for node_id, node in self.nodes.items():
            color = (255, 0, 0) if node_id == self.active_node else (255, 255, 255)
            cv2.circle(self.img, (node['x'], node['y']), MIN_DIST_TO_NODE // 2, color)

        # Draw the detection trail
        points = self.results
        if DRAW_TRAIL and len(points) > 1:
            for p_idx in range(len(points) - 1):
                try:
                    x1, y1 = map(int, points[p_idx])
                    x2, y2 = map(int, points[p_idx + 1])
                except (ValueError, TypeError):
                    pass
                else:
                    cv2.line(self.img, (x1, y1), (x2, y2), color=(0, 255, 0), thickness=2)

        # Draw the Kalman filter predictions trail
        cv2.drawMarker(self.img, position=self.last_kf_pos, color=(0, 0, 255))
        points = self.kf_results
        if DRAW_KF_TRAIL and len(points) > 1:
            for p_idx in range(len(points) - 1):
                try:
                    x1, y1 = map(int, points[p_idx])
                    x2, y2 = map(int, points[p_idx + 1])
                except (ValueError, TypeError):
                    pass
                else:
                    cv2.line(self.img, (x1, y1), (x2, y2), color=(50, 50, 255), thickness=1)

    def apply(self, frame):
        t0 = cv2.getTickCount()

        h_start = self.id * (FRAME_HEIGHT + FRAME_METADATA)
        h_end = self.id * (FRAME_HEIGHT + FRAME_METADATA) + FRAME_HEIGHT
        self.img = frame[h_start:h_end, :]

        metadata = extract_metadata(frame[h_end:h_end + FRAME_METADATA, -FRAME_METADATA_BYTE//3:])

        frame_of_interest = not ('index' not in metadata or metadata['index'] == self.__last_frame_idx)

        if not frame_of_interest:
            return

        else:
            try:
                self.__last_frame_idx = metadata['index']
                self.__last_frame_tickstamp = metadata['tickst']
            except KeyError as e:
                logging.exception(e)

            # It takes time to fire up the cameras, so first frames might be zeros.
            # Check until we have a mask
            if not self.has_mask:
                foi = cv2.cvtColor(self.img, cv2.COLOR_RGB2GRAY)
                if np.mean(foi) > 15:
                    logging.info('Grabbing mask')
                    self.make_mask(cv2.cvtColor(self.img, cv2.COLOR_RGB2GRAY), global_threshold=self.thresh_mask)

            # cut out search window from image and from mask, if needed
            if self.search_point is None:
                foi = cv2.cvtColor(self.img, cv2.COLOR_RGB2GRAY)
                mask = self.mask_frame // 255
                foi_ofs = (0, 0)
            else:
                p1, p2 = self.get_search_window()
                foi = cv2.cvtColor(self.img[p1[1]:p2[1], p1[0]:p2[0]], cv2.COLOR_RGB2GRAY)
                foi_ofs = p1
                mask = self.mask_frame[p1[1]:p2[1], p1[0]:p2[0]] // 255
                # tid = self.id
                # print(tid, self.img.shape, self.search_point, 'w', (p1[0], p2[0]), 'h', (p1[1], p2[1]))

            # cv2.imshow('foi {}'.format(self.id), foi)

            masked = cv2.bitwise_not(foi) * (mask)
            masked = cv2.morphologyEx(masked, cv2.MORPH_OPEN, KERNEL_3)

            _, thresh = cv2.threshold(masked, self.thresh_detect, 255, cv2.THRESH_BINARY)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, KERNEL_3)

            _, contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # find largest contour
            largest_cnt, largest_area = None, 0
            sum_area = 0
            for cnt in contours:
                area = int(cv2.contourArea(cnt))
                if area > MIN_MOUSE_AREA:
                    sum_area += area
                    if area > largest_area:
                        largest_area = area
                        largest_cnt = cnt

            # Correct coordinates for search window location
            if largest_cnt is not None:
                largest_cnt[:, :, 0] = largest_cnt[:, :, 0] + foi_ofs[0]
                largest_cnt[:, :, 1] = largest_cnt[:, :, 1] + foi_ofs[1]

            self.contours = contours
            self.largest_contour = largest_cnt

            closest_distance = 1e12

            self.active_node = None
            if largest_cnt is None:
                self.kf_age += 1
                self.results.appendleft(None)
                self.search_window_size = min(int(self.search_window_size * 1.5), max(FRAME_WIDTH, FRAME_HEIGHT * 2))
            else:
                # center coordinates of contour
                self.search_window_size = SEARCH_WINDOW_SIZE
                cx, cy = centroid(largest_cnt)


                self.results.appendleft((cx, cy))
                self.kf.correct(cx, cy)
                self.kf_age = 0

                # Find closest node
                for node_id, node in self.nodes.items():
                    dist = distance(cx, cy, node['x'], node['y'])
                    if dist < closest_distance and dist < MIN_DIST_TO_NODE:
                        closest_distance = dist
                        self.active_node = node_id

            if self.last_node != self.active_node and self.active_node is not None:
                self.last_node = self.active_node
                self.node_updated_presented = False
                logging.info('Tracker {}: {} {}'.format(self.id, '    ' * self.id, self.last_node))

            # Kalman filter of position
            # Only predict position if the age of the last measurement is low enough
            # Else assume KF has no useful information about mouse position either.
            if self.kf_age < KF_REGISTRATION_AGE:
                kf_res = self.kf.predict()
                kfx = min(max(0, int(kf_res[0])), FRAME_WIDTH)
                kfy = min(max(0, int(kf_res[1])), FRAME_HEIGHT)

                self.kf_results.appendleft((kfx, kfy))

                self.last_kf_pos = (kfx, kfy)
                self.search_point = self.last_kf_pos

            else:
                self.search_point = None
                self.last_kf_pos = None
                self.kf_results.appendleft(None)

            # Detect LED state (mean value of red channel around led center)
            led_img = self.img[self.led_pos[1]-1:self.led_pos[1]+2, self.led_pos[0]-1:self.led_pos[0]+2, 0]
            self.led_state = np.mean(led_img) > self.thresh_led

            self.n_frames += 1

            elapsed = (cv2.getTickCount() - t0) / cv2.getTickFrequency() * 1000
            self._t_track.appendleft(elapsed)
