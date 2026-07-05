import argparse
import time

import cv2


def parse_args():
    parser = argparse.ArgumentParser(
        description="Use a webcam to detect and decode multiple QR codes at the same time."
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Camera index. Usually 0 is the built-in or first USB camera.",
    )
    parser.add_argument("--width", type=int, default=1280, help="Capture width.")
    parser.add_argument("--height", type=int, default=720, help="Capture height.")
    parser.add_argument(
        "--show-empty",
        action="store_true",
        help="Draw detected QR boxes even when decoding text failed.",
    )
    return parser.parse_args()


def draw_qr_result(frame, index, text, points):
    corners = points.astype(int).reshape(-1, 2)

    for i in range(len(corners)):
        start = tuple(corners[i])
        end = tuple(corners[(i + 1) % len(corners)])
        cv2.line(frame, start, end, (0, 255, 0), 2)

    x, y = corners.min(axis=0)
    label = f"{index}: {text}" if text else f"{index}: <decode failed>"
    label_y = max(24, y - 10)
    cv2.putText(
        frame,
        label,
        (x, label_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )


def main():
    args = parse_args()
    detector = cv2.QRCodeDetector()
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)

    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open camera {args.camera}. Try another index, for example --camera 1."
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    seen = {}
    print("Camera started. Press q or Esc to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to read from camera.")
            break

        decoded_ok, decoded_info, points, _ = detector.detectAndDecodeMulti(frame)
        current_count = 0

        if decoded_ok and points is not None:
            for index, (text, qr_points) in enumerate(zip(decoded_info, points), start=1):
                if text or args.show_empty:
                    current_count += 1
                    draw_qr_result(frame, index, text, qr_points)

                if text:
                    now = time.time()
                    last_seen = seen.get(text, 0)
                    if now - last_seen > 1.0:
                        print(f"[QR] {text}")
                    seen[text] = now

        cv2.putText(
            frame,
            f"QR codes: {current_count}",
            (20, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Multi QR camera scanner", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
