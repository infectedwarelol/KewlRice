import datetime
import math


def mix(first, second, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, second))


def time_of_day(hour):
    if hour >= 20 or hour < 5:
        return "night"
    if hour < 7:
        return "dawn"
    if hour >= 17:
        return "dusk"
    return "day"


def sun_direction(hour):
    angle = 2 * math.pi * (hour - 13.5) / 24
    x, y, z = math.sin(angle), 0.35 + 0.15 * max(0.0, math.cos(angle)), math.cos(angle)
    length = math.sqrt(x * x + y * y + z * z)
    return x / length, y / length, z / length


class Sky:
    def __init__(self, now=None):
        now = now or datetime.datetime.now().astimezone()
        hour = now.hour + now.minute / 60
        self.time_of_day = time_of_day(hour)
        self.light = sun_direction(hour)
