#!/usr/bin/env bash
awk '
function size(kib) {
    if (kib < 1048576) return sprintf("%dMb", kib / 1024 + 0.5)
    return sprintf("%.1fGb", kib / 1048576)
}
/^MemTotal:/ { total = $2 }
/^MemAvailable:/ { available = $2 }
END {
    if (total <= 0) { print "{\"text\":\"\"}"; exit }
    used = total - available
    printf "{\"text\":\"%s/%s\",\"tooltip\":\"RAM %s of %s (%d%%)\",\"percentage\":%d}\n", size(used), size(total), size(used), size(total), used * 100 / total + 0.5, used * 100 / total + 0.5
}' /proc/meminfo
