import subprocess


def pixbuf_to_png(pixbuf):
    _, data = pixbuf.save_to_bufferv("png", [], [])
    return data


def copy_image(pixbuf):
    subprocess.run(
        ["wl-copy", "--type", "image/png"],
        input=pixbuf_to_png(pixbuf),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
