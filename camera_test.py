import cv2

for index in range(10):

    print(f"\n🔍 Testing camera index {index}")

    cap = cv2.VideoCapture(
        index,
        cv2.CAP_V4L2
    )

    if not cap.isOpened():
        print(f"❌ Index {index}: cannot open")
        cap.release()
        continue

    # E-con camera may need MJPG
    cap.set(
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(
            "M", "J", "P", "G"
        )
    )

    ret, frame = cap.read()

    if ret and frame is not None:

        print(f"✅ Index {index}: WORKING")
        print(f"   Frame shape: {frame.shape}")

        cv2.imwrite(
            f"camera_{index}.jpg",
            frame
        )

    else:

        print(
            f"⚠️ Index {index}: opened "
            "but frame failed"
        )

    cap.release()