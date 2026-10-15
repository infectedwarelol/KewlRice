#include <math.h>
#include <stddef.h>
#include <stdint.h>

void globe_prepare(int size, double pitch_degrees, int texture_width, int texture_height, float *u, float *v, float *coverage)
{
    double radius = size / 2.0;
    double pitch = pitch_degrees * M_PI / 180.0;
    double cos_pitch = cos(pitch);
    double sin_pitch = sin(pitch);
    for (int row = 0; row < size; row++) {
        double sy = (radius - (row + 0.5)) / radius;
        for (int column = 0; column < size; column++) {
            int index = row * size + column;
            double sx = ((column + 0.5) - radius) / radius;
            double distance_squared = sx * sx + sy * sy;
            double edge = (1.0 - sqrt(distance_squared)) * radius + 0.5;
            if (edge <= 0.0) {
                coverage[index] = 0.0f;
                u[index] = 0.0f;
                v[index] = 0.0f;
                continue;
            }
            coverage[index] = edge >= 1.0 ? 1.0f : (float)edge;
            double sz = distance_squared < 1.0 ? sqrt(1.0 - distance_squared) : 0.0;
            double wy = sy * cos_pitch + sz * sin_pitch;
            double wz = -sy * sin_pitch + sz * cos_pitch;
            if (wy > 1.0) {
                wy = 1.0;
            }
            if (wy < -1.0) {
                wy = -1.0;
            }
            double latitude = asin(wy);
            double longitude = atan2(sx, wz);
            u[index] = (float)((longitude / (2.0 * M_PI) + 0.5) * texture_width);
            v[index] = (float)((0.5 - latitude / M_PI) * texture_height);
        }
    }
}

static inline uint32_t blend(uint32_t first, uint32_t second, uint32_t weight)
{
    uint32_t inverse = 256 - weight;
    uint32_t red_blue = (((first & 0x00FF00FFu) * inverse + (second & 0x00FF00FFu) * weight) >> 8) & 0x00FF00FFu;
    uint32_t alpha_green = ((((first >> 8) & 0x00FF00FFu) * inverse + ((second >> 8) & 0x00FF00FFu) * weight)) & 0xFF00FF00u;
    return red_blue | alpha_green;
}

static inline uint32_t scale(uint32_t pixel, uint32_t amount)
{
    uint32_t red_blue = (((pixel & 0x00FF00FFu) * amount) >> 8) & 0x00FF00FFu;
    uint32_t alpha_green = (((pixel >> 8) & 0x00FF00FFu) * amount) & 0xFF00FF00u;
    return red_blue | alpha_green;
}

void globe_render(const uint32_t *texture, int texture_width, int texture_height, const float *u, const float *v,
                  const float *coverage, int size, uint32_t *output, int output_stride, const uint32_t *light,
                  int light_stride, double shift_texels)
{
    int width_mask = texture_width - 1;
    float shift = (float)shift_texels;
#pragma omp parallel for schedule(static)
    for (int row = 0; row < size; row++) {
        uint32_t *line = (uint32_t *)((uint8_t *)output + (size_t)row * output_stride);
        const float *row_u = u + (size_t)row * size;
        const float *row_v = v + (size_t)row * size;
        const float *row_coverage = coverage + (size_t)row * size;
        const uint32_t *row_light = light ? (const uint32_t *)((const uint8_t *)light + (size_t)row * light_stride) : NULL;
        for (int column = 0; column < size; column++) {
            float cover = row_coverage[column];
            if (cover <= 0.0f) {
                line[column] = 0;
                continue;
            }
            float fu = row_u[column] + shift - 0.5f;
            float fv = row_v[column] - 0.5f;
            int ix = (int)(fu * 256.0f + 65536.0f * 256.0f);
            int iy = (int)(fv * 256.0f);
            int x0 = (ix >> 8) & width_mask;
            int x1 = (x0 + 1) & width_mask;
            int y0 = iy >> 8;
            if (iy < 0) {
                y0 = 0;
                iy = 0;
            }
            int y1 = y0 + 1;
            if (y0 >= texture_height - 1) {
                y0 = texture_height - 1;
                y1 = y0;
            }
            uint32_t weight_x = (uint32_t)(ix & 0xFF);
            uint32_t weight_y = (uint32_t)(iy & 0xFF);
            const uint32_t *top = texture + (size_t)y0 * texture_width;
            const uint32_t *bottom = texture + (size_t)y1 * texture_width;
            uint32_t upper = blend(top[x0], top[x1], weight_x);
            uint32_t lower = blend(bottom[x0], bottom[x1], weight_x);
            uint32_t pixel = blend(upper, lower, weight_y);
            if (row_light) {
                uint32_t shade = row_light[column];
                pixel = shade + scale(pixel, 256 - ((shade >> 24) + ((shade >> 24) >> 7)));
            }
            line[column] = cover >= 1.0f ? pixel : scale(pixel, (uint32_t)(cover * 256.0f));
        }
    }
}
