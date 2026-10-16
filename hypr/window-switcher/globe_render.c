#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#if defined(__AVX2__) && defined(__FMA__)
#include <immintrin.h>
#endif

#define MAX_LEVELS 16
#define GRADE_STEPS 4096
#define BLOOM_RADIUS 4
#define POLE_TEXELS 3.0f
#define DISTANCE_CAP 255.0f
#define HALO_STEPS 2048
#define HALO_RANGE 0.5f
#define BRIGHT_SCALE 64.0f
#define SHADOW_TEXELS 0.9f
#define WRAP_BIAS_TEXELS 4096.0f

typedef struct {
    float light[3];
    float key_color[3];
    float rim_color[3];
    float sky_ambient[3];
    float ground_ambient[3];
    float atmosphere_lit[3];
    float atmosphere_dark[3];
    float emissive_color[3];
    float cloud_color[3];
    float warm_color[3];
    float warm_amount;
    float bump;
    float pitch_degrees;
    float shift;
    float cloud_shift;
    float exposure;
    float bloom_threshold;
    float bloom_strength;
    float grain_amount;
    float halo_extent;
    uint32_t grain_seed;
} GlobeParams;

typedef struct {
    float ocean_deep[3];
    float ocean_shelf[3];
    float land_low[3];
    float land_high[3];
    float lights_gain;
    uint32_t seed;
} BakeParams;

typedef struct {
    int offsets[MAX_LEVELS];
    int widths[MAX_LEVELS];
    int heights[MAX_LEVELS];
    float scales[MAX_LEVELS];
    int count;
} MipGeometry;

static MipGeometry geometry;
static const uint32_t *color_texels;
static const uint32_t *surface_texels;
static uint32_t color_poles[2];
static uint32_t surface_poles[2];
static float grade_table[3][GRADE_STEPS + 1];
static float halo_table[HALO_STEPS + 1];

static inline float clampf(float value, float low, float high)
{
    return value < low ? low : (value > high ? high : value);
}

static inline float smoothstepf(float edge0, float edge1, float value)
{
    float t = clampf((value - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

static inline float mixf(float first, float second, float amount)
{
    return first + (second - first) * amount;
}

static inline uint32_t blend(uint32_t first, uint32_t second, uint32_t weight)
{
    uint32_t inverse = 256 - weight;
    uint32_t red_blue = (((first & 0x00FF00FFu) * inverse + (second & 0x00FF00FFu) * weight) >> 8) & 0x00FF00FFu;
    uint32_t alpha_green = ((((first >> 8) & 0x00FF00FFu) * inverse + ((second >> 8) & 0x00FF00FFu) * weight)) & 0xFF00FF00u;
    return red_blue | alpha_green;
}

static inline uint32_t channel(uint32_t pixel, int shift)
{
    return (pixel >> shift) & 0xFFu;
}

static inline uint32_t pack(uint32_t alpha, uint32_t red, uint32_t green, uint32_t blue)
{
    return (alpha << 24) | (red << 16) | (green << 8) | blue;
}

static inline uint32_t to_byte(float value)
{
    return (uint32_t)clampf(value * 255.0f + 0.5f, 0.0f, 255.0f);
}

int globe_mip_levels(int width, int height)
{
    int levels = 1;
    while (width > 1 && height > 1 && levels < MAX_LEVELS) {
        width >>= 1;
        height >>= 1;
        levels++;
    }
    return levels;
}

void globe_build_mips(uint32_t *chain, int width, int height)
{
    int levels = globe_mip_levels(width, height);
    uint32_t *source = chain;
    for (int level = 1; level < levels; level++) {
        int source_width = width >> (level - 1);
        int target_width = width >> level;
        int target_height = height >> level;
        uint32_t *target = source + (size_t)source_width * (size_t)(height >> (level - 1));
#pragma omp parallel for schedule(static)
        for (int row = 0; row < target_height; row++) {
            const uint32_t *upper = source + (size_t)(2 * row) * source_width;
            const uint32_t *lower = upper + source_width;
            for (int column = 0; column < target_width; column++) {
                uint32_t a = upper[2 * column], b = upper[2 * column + 1], c = lower[2 * column], d = lower[2 * column + 1];
                uint32_t result = 0;
                for (int shift = 0; shift < 32; shift += 8) {
                    uint32_t sum = channel(a, shift) + channel(b, shift) + channel(c, shift) + channel(d, shift);
                    result |= ((sum + 2) >> 2) << shift;
                }
                target[(size_t)row * target_width + column] = result;
            }
        }
        source = target;
    }
}

static uint32_t row_average(const uint32_t *row, int width)
{
    uint64_t sums[4] = {0, 0, 0, 0};
    for (int column = 0; column < width; column++) {
        for (int index = 0; index < 4; index++) {
            sums[index] += channel(row[column], index * 8);
        }
    }
    uint32_t result = 0;
    for (int index = 0; index < 4; index++) {
        result |= (uint32_t)(sums[index] / (uint64_t)width) << (index * 8);
    }
    return result;
}

void globe_bind(const uint32_t *color, const uint32_t *surface, int width, int height)
{
    geometry.count = globe_mip_levels(width, height);
    int offset = 0;
    for (int level = 0; level < geometry.count; level++) {
        geometry.offsets[level] = offset;
        geometry.widths[level] = width >> level;
        geometry.heights[level] = height >> level;
        geometry.scales[level] = 1.0f / (float)(1 << level);
        offset += geometry.widths[level] * geometry.heights[level];
    }
    color_texels = color;
    surface_texels = surface;
    color_poles[0] = row_average(color, width);
    color_poles[1] = row_average(color + (size_t)(height - 1) * width, width);
    surface_poles[0] = row_average(surface, width);
    surface_poles[1] = row_average(surface + (size_t)(height - 1) * width, width);
}

void globe_grade(const float *gamma, const float *lift)
{
    for (int step = 0; step <= HALO_STEPS; step++) {
        float outside = (float)step * HALO_RANGE / HALO_STEPS;
        halo_table[step] = fminf(1.0f, 0.85f * expf(-outside / 0.016f) + 0.2f * expf(-outside / 0.075f));
    }
    for (int component = 0; component < 3; component++) {
        for (int step = 0; step <= GRADE_STEPS; step++) {
            float value = (float)step / GRADE_STEPS;
            value = powf(value, gamma[component]);
            value = value + lift[component] * (1.0f - value);
            float encoded = value <= 0.0031308f ? value * 12.92f : 1.055f * powf(value, 1.0f / 2.4f) - 0.055f;
            grade_table[component][step] = clampf(encoded, 0.0f, 1.0f) * 255.0f;
        }
    }
}

static int project(double sx, double sy, double cos_pitch, double sin_pitch, int texture_width, int texture_height, double *u, double *v)
{
    double distance_squared = sx * sx + sy * sy;
    double sz = distance_squared < 1.0 ? sqrt(1.0 - distance_squared) : 0.0;
    if (distance_squared > 1.0) {
        double length = sqrt(distance_squared);
        sx /= length;
        sy /= length;
    }
    double wy = sy * cos_pitch + sz * sin_pitch;
    double wz = -sy * sin_pitch + sz * cos_pitch;
    wy = wy > 1.0 ? 1.0 : (wy < -1.0 ? -1.0 : wy);
    *u = (atan2(sx, wz) / (2.0 * M_PI) + 0.5) * texture_width;
    *v = (0.5 - asin(wy) / M_PI) * texture_height;
    return distance_squared <= 1.0;
}

static double wrapped_difference(double first, double second, int texture_width)
{
    double difference = first - second;
    if (difference > texture_width / 2.0) {
        difference -= texture_width;
    } else if (difference < -texture_width / 2.0) {
        difference += texture_width;
    }
    return difference;
}

void globe_prepare(int size, float radius, double pitch_degrees, int texture_width, int texture_height, float *u, float *v, float *lod)
{
    double pitch = pitch_degrees * M_PI / 180.0;
    double cos_pitch = cos(pitch);
    double sin_pitch = sin(pitch);
    double center = size / 2.0;
    double step = 1.0 / radius;
#pragma omp parallel for schedule(static)
    for (int row = 0; row < size; row++) {
        double sy = (center - (row + 0.5)) / radius;
        for (int column = 0; column < size; column++) {
            size_t index = (size_t)row * size + column;
            double sx = ((column + 0.5) - center) / radius;
            if (sx * sx + sy * sy > (1.0 + 2.0 * step) * (1.0 + 2.0 * step)) {
                u[index] = 0.0f;
                v[index] = 0.0f;
                lod[index] = 0.0f;
                continue;
            }
            double pu, pv, ru, rv, du, dv;
            project(sx, sy, cos_pitch, sin_pitch, texture_width, texture_height, &pu, &pv);
            project(sx + step, sy, cos_pitch, sin_pitch, texture_width, texture_height, &ru, &rv);
            project(sx, sy - step, cos_pitch, sin_pitch, texture_width, texture_height, &du, &dv);
            double horizontal_u = wrapped_difference(ru, pu, texture_width), horizontal_v = rv - pv;
            double vertical_u = wrapped_difference(du, pu, texture_width), vertical_v = dv - pv;
            double footprint = fmax(horizontal_u * horizontal_u + horizontal_v * horizontal_v, vertical_u * vertical_u + vertical_v * vertical_v);
            double level = footprint > 1.0 ? 0.5 * log2(footprint) - 0.25 : 0.0;
            u[index] = (float)pu;
            v[index] = (float)pv;
            lod[index] = (float)(level < 0.0 ? 0.0 : level);
        }
    }
}

static inline void level_taps(int level, float u, float v, int *taps, uint32_t *weight_x, uint32_t *weight_y)
{
    int width = geometry.widths[0] >> level;
    int height = geometry.heights[0] >> level;
    int texels = geometry.widths[0] * geometry.heights[0];
    int offset = 4 * (texels - (texels >> (2 * level))) / 3;
    uint32_t scale_bits = (uint32_t)(127 - level) << 23;
    float scale;
    memcpy(&scale, &scale_bits, sizeof(scale));
    float fu = u * scale - 0.5f;
    float fv = clampf(v * scale - 0.5f, 0.0f, (float)(height - 1));
    int ix = (int)((fu + WRAP_BIAS_TEXELS) * 256.0f);
    int iy = (int)(fv * 256.0f);
    int x0 = (ix >> 8) & (width - 1);
    int x1 = (x0 + 1) & (width - 1);
    int y0 = iy >> 8;
    int y1 = y0 + 1 < height ? y0 + 1 : height - 1;
    int top = offset + y0 * width;
    int bottom = offset + y1 * width;
    taps[0] = top + x0;
    taps[1] = top + x1;
    taps[2] = bottom + x0;
    taps[3] = bottom + x1;
    *weight_x = (uint32_t)(ix & 0xFF);
    *weight_y = (uint32_t)(iy & 0xFF);
}

static inline uint32_t fetch(const uint32_t *texels, const int *taps, uint32_t weight_x, uint32_t weight_y)
{
    return blend(blend(texels[taps[0]], texels[taps[1]], weight_x), blend(texels[taps[2]], texels[taps[3]], weight_x), weight_y);
}

static inline float tone_map(float value)
{
    value = value > 0.0f ? value : 0.0f;
    float mapped = (value * (2.51f * value + 0.03f)) / (value * (2.43f * value + 0.59f) + 0.14f);
    return mapped < 1.0f ? mapped : 1.0f;
}

static inline float graded(int component, float value)
{
    return grade_table[component][(int)(value * GRADE_STEPS)];
}

static inline float grain(int column, int row, uint32_t seed)
{
    uint32_t hash = (uint32_t)column * 0x8da6b343u ^ (uint32_t)row * 0xd8163841u ^ seed;
    hash ^= hash >> 15;
    hash *= 0x2c1b3c6du;
    hash ^= hash >> 12;
    return (float)(hash & 0xFFFF) / 32767.5f - 1.0f;
}

static inline float halo_density(float outside)
{
    return halo_table[(int)(clampf(outside, 0.0f, HALO_RANGE) * (HALO_STEPS / HALO_RANGE))];
}

static const float blur_weights[BLOOM_RADIUS + 1] = {0.2041f, 0.1801f, 0.1238f, 0.0663f, 0.0276f};

static void blur_horizontal(const float *source, float *target, int size)
{
    int span = size * 3;
#pragma omp parallel for schedule(static)
    for (int row = 0; row < size; row++) {
        const float *line = source + (size_t)row * span;
        float *out = target + (size_t)row * span;
        for (int index = 0; index < span; index++) {
            out[index] = line[index] * blur_weights[0];
        }
        for (int offset = 1; offset <= BLOOM_RADIUS; offset++) {
            int shift = offset * 3;
            float weight = blur_weights[offset];
            for (int index = shift; index < span; index++) {
                out[index] += line[index - shift] * weight;
            }
            for (int index = 0; index < span - shift; index++) {
                out[index] += line[index + shift] * weight;
            }
        }
    }
}

static void blur_vertical(const float *source, float *target, int size)
{
    int span = size * 3;
#pragma omp parallel for schedule(static)
    for (int row = 0; row < size; row++) {
        float *out = target + (size_t)row * span;
        const float *center = source + (size_t)row * span;
        for (int index = 0; index < span; index++) {
            out[index] = center[index] * blur_weights[0];
        }
        for (int offset = 1; offset <= BLOOM_RADIUS; offset++) {
            float weight = blur_weights[offset];
            if (row - offset >= 0) {
                const float *above = source + (size_t)(row - offset) * span;
                for (int index = 0; index < span; index++) {
                    out[index] += above[index] * weight;
                }
            }
            if (row + offset < size) {
                const float *below = source + (size_t)(row + offset) * span;
                for (int index = 0; index < span; index++) {
                    out[index] += below[index] * weight;
                }
            }
        }
    }
}

static void downsample_bright(const uint32_t *bright, int size, float *accumulator, int quarter)
{
    float normalize = 1.0f / (16.0f * BRIGHT_SCALE);
#pragma omp parallel for schedule(static)
    for (int row = 0; row < quarter; row++) {
        for (int column = 0; column < quarter; column++) {
            uint32_t sums[3] = {0, 0, 0};
            for (int y = row * 4; y < row * 4 + 4 && y < size; y++) {
                for (int x = column * 4; x < column * 4 + 4 && x < size; x++) {
                    uint32_t pixel = bright[(size_t)y * size + x];
                    sums[0] += channel(pixel, 16);
                    sums[1] += channel(pixel, 8);
                    sums[2] += channel(pixel, 0);
                }
            }
            float *out = accumulator + ((size_t)row * quarter + column) * 3;
            out[0] = sums[0] * normalize;
            out[1] = sums[1] * normalize;
            out[2] = sums[2] * normalize;
        }
    }
}

typedef struct {
    const uint32_t *color_source;
    const uint32_t *surface_source;
    uint32_t color_poles[2];
    uint32_t surface_poles[2];
    float cos_pitch, sin_pitch;
    float light_x, light_y, light_z;
    float half_x, half_y, half_z;
    float rim_x, rim_y, rim_z;
    float planar_x, planar_y, planar_length, backlight;
    float key[3], warm[3], rim_color[3], sky_ambient[3], ground_ambient[3];
    float atmosphere_lit[3], atmosphere_dark[3], emissive_color[3], cloud_color[3];
    float warm_amount, bump, exposure, shift, cloud_shift, bloom_threshold, bloom_strength, grain_amount;
    uint32_t grain_seed;
    float center, radius, inverse_radius, aberration, shadow_shift_x, shadow_shift_y, texture_height;
    int last_level, quarter, width_shift, base_height, texels;
} Frame;

typedef struct {
    const float *u;
    const float *v;
    const float *lod;
    const float *glow;
    float sy;
    int row;
    uint32_t *line;
    uint32_t *bright;
} Row;

static inline void bloom_at(const Frame *frame, const Row *row, int column, float *glow)
{
    float bloom_x = (column + 0.5f) * 0.25f - 0.5f;
    int left = (int)floorf(bloom_x);
    float weight_x = bloom_x - (float)left;
    int right = left + 1 < frame->quarter ? left + 1 : frame->quarter - 1;
    left = left < 0 ? 0 : left;
    for (int component = 0; component < 3; component++) {
        glow[component] = mixf(row->glow[left * 3 + component], row->glow[right * 3 + component], weight_x);
    }
}

static inline void shade_halo(const Frame *frame, float sx, float sy, float distance, const float *glow, float *halo, float *halo_alpha)
{
    float outside = distance - 1.0f;
    float lit = clampf(((sx * frame->planar_x + sy * frame->planar_y) / distance) * frame->planar_length * 0.8f + 0.42f + 0.6f * frame->backlight, 0.0f, 1.0f);
    lit = lit * lit * (3.0f - 2.0f * lit);
    float strength = 0.35f + 0.65f * lit;
    float densities[3] = {
        halo_density(outside - frame->aberration) * strength,
        halo_density(outside) * strength,
        halo_density(outside + frame->aberration) * strength,
    };
    float alpha = fmaxf(densities[0], fmaxf(densities[1], densities[2]));
    float brightest = 0.0f;
    for (int component = 0; component < 3; component++) {
        float tint = mixf(frame->atmosphere_dark[component], frame->atmosphere_lit[component], lit) * (0.5f + 1.3f * lit);
        halo[component] = tint * densities[component] + glow[component];
        brightest = fmaxf(brightest, halo[component]);
    }
    *halo_alpha = clampf(fmaxf(alpha, brightest * 0.5f), 0.0f, 1.0f);
}

static inline void shade_planet(const Frame *frame, const Row *row, int column, float sx, float sy, float distance_squared,
                                float distance, float coverage, const float *glow, float *planet, float *bright_light)
{
    float sz = sqrtf(1.0f - fminf(distance_squared, 1.0f));
    float limb = distance > 1.0f ? 1.0f / distance : 1.0f;
    float normal_x = sx * limb, normal_y = sy * limb;

    float pixel_u = row->u[column] + frame->shift, pixel_v = row->v[column], pixel_lod = row->lod[column];
    int level = (int)pixel_lod;
    level = level < frame->last_level ? level : frame->last_level;
    int next_level = level + 1 < frame->last_level ? level + 1 : frame->last_level;
    uint32_t mip_weight = (uint32_t)(clampf(pixel_lod - (float)level, 0.0f, 1.0f) * 256.0f);
    int taps[4];
    uint32_t weight_x, weight_y;
    level_taps(level, pixel_u, pixel_v, taps, &weight_x, &weight_y);
    uint32_t color = fetch(frame->color_source, taps, weight_x, weight_y);
    uint32_t surface = fetch(frame->surface_source, taps, weight_x, weight_y);
    level_taps(next_level, pixel_u, pixel_v, taps, &weight_x, &weight_y);
    color = blend(color, fetch(frame->color_source, taps, weight_x, weight_y), mip_weight);
    surface = blend(surface, fetch(frame->surface_source, taps, weight_x, weight_y), mip_weight);
    float pole_distance = fminf(pixel_v, frame->texture_height - pixel_v);
    uint32_t pole_weight = (uint32_t)(clampf(1.0f - pole_distance / POLE_TEXELS, 0.0f, 1.0f) * 256.0f);
    uint32_t north = 0u - (uint32_t)(pixel_v < frame->texture_height * 0.5f);
    color = blend(color, (frame->color_poles[0] & north) | (frame->color_poles[1] & ~north), pole_weight);
    surface = blend(surface, (frame->surface_poles[0] & north) | (frame->surface_poles[1] & ~north), pole_weight);
    int cloud_level = (int)(pixel_lod + 1.5f);
    cloud_level = cloud_level < frame->last_level ? cloud_level : frame->last_level;
    level_taps(cloud_level, row->u[column] + frame->cloud_shift, pixel_v, taps, &weight_x, &weight_y);
    float cloud_top_left = channel(frame->surface_source[taps[0]], 24) * (1.0f / 255.0f);
    float cloud_top_right = channel(frame->surface_source[taps[1]], 24) * (1.0f / 255.0f);
    float cloud_bottom_left = channel(frame->surface_source[taps[2]], 24) * (1.0f / 255.0f);
    float cloud_bottom_right = channel(frame->surface_source[taps[3]], 24) * (1.0f / 255.0f);
    float cloud_x = weight_x * (1.0f / 256.0f), cloud_y = weight_y * (1.0f / 256.0f);
    float cloud = mixf(mixf(cloud_top_left, cloud_top_right, cloud_x), mixf(cloud_bottom_left, cloud_bottom_right, cloud_x), cloud_y);
    float shadow_x = clampf(cloud_x - frame->shadow_shift_x, 0.0f, 1.0f), shadow_y = clampf(cloud_y + frame->shadow_shift_y, 0.0f, 1.0f);
    float cloud_shadow = mixf(mixf(cloud_top_left, cloud_top_right, shadow_x), mixf(cloud_bottom_left, cloud_bottom_right, shadow_x), shadow_y);

    float cos_pitch = frame->cos_pitch, sin_pitch = frame->sin_pitch;
    float world_y = normal_y * cos_pitch + sz * sin_pitch;
    float world_z = -normal_y * sin_pitch + sz * cos_pitch;
    float latitude_cos = sqrtf(normal_x * normal_x + world_z * world_z);
    float inverse_cos = 1.0f / fmaxf(latitude_cos, 1e-4f);
    float east_x = world_z * inverse_cos, east_world_z = -normal_x * inverse_cos;
    float east_y = -east_world_z * sin_pitch, east_z = east_world_z * cos_pitch;
    float north_x = -world_y * normal_x * inverse_cos;
    float north_world_z = -world_y * world_z * inverse_cos;
    float north_y = latitude_cos * cos_pitch - north_world_z * sin_pitch;
    float north_z = latitude_cos * sin_pitch + north_world_z * cos_pitch;
    float slope_east = ((float)channel(surface, 16) - 128.0f) * frame->bump;
    float slope_north = ((float)channel(surface, 8) - 128.0f) * frame->bump;
    float inverse_length = 1.0f / sqrtf(1.0f + slope_east * slope_east + slope_north * slope_north);
    float bumped_x = (normal_x - slope_east * east_x - slope_north * north_x) * inverse_length;
    float bumped_y = (normal_y - slope_east * east_y - slope_north * north_y) * inverse_length;
    float bumped_z = (sz - slope_east * east_z - slope_north * north_z) * inverse_length;

    float geometric = normal_x * frame->light_x + normal_y * frame->light_y + sz * frame->light_z;
    float facing = bumped_x * frame->light_x + bumped_y * frame->light_y + bumped_z * frame->light_z;
    float diffuse = clampf((facing + 0.3f) * (1.0f / 1.3f), 0.0f, 1.0f) * smoothstepf(-0.3f, 0.15f, geometric);
    float daylight = smoothstepf(-0.12f, 0.32f, geometric);
    float band_distance = (geometric - 0.03f) * (1.0f / 0.24f);
    float band = frame->warm_amount * clampf(1.0f - band_distance * band_distance, 0.0f, 1.0f);
    float rim = clampf(bumped_x * frame->rim_x + bumped_y * frame->rim_y + bumped_z * frame->rim_z, 0.0f, 1.0f);
    float sky = bumped_y * 0.5f + 0.5f;
    float half_facing = clampf(bumped_x * frame->half_x + bumped_y * frame->half_y + bumped_z * frame->half_z, 0.0f, 1.0f);
    half_facing = half_facing > 0.3f ? half_facing : 0.0f;
    float broad = half_facing * half_facing;
    broad *= broad;
    broad *= broad;
    float glossy = broad * broad;
    glossy *= glossy;
    glossy *= glossy;
    float grazing = 1.0f - sz;
    float grazing_squared = grazing * grazing;
    float fresnel = 0.04f + 0.96f * grazing_squared * grazing_squared * grazing;
    float specular = channel(surface, 0) * (1.0f / 255.0f) * (1.0f - cloud) * (glossy * 1.0f + broad * 0.03f) * (1.0f + 4.0f * fresnel) * daylight;
    float shadow = 1.0f - 0.45f * cloud_shadow * daylight;
    float emissive = channel(color, 24) * (1.0f / 255.0f);
    float night = 1.0f - daylight;
    emissive *= emissive * night * night * (1.0f - 0.6f * cloud);
    float haze = grazing_squared * (0.35f + 0.25f * grazing);
    float haze_light = 0.25f + 1.1f * clampf(geometric + 0.25f, 0.0f, 1.0f);
    float haze_mix = smoothstepf(-0.35f, 0.5f, geometric);
    for (int component = 0; component < 3; component++) {
        float encoded = channel(color, 16 - 8 * component) * (1.0f / 255.0f);
        float albedo = encoded * (encoded * (encoded * 0.305306011f + 0.682171111f) + 0.012522878f);
        float light = mixf(frame->key[component], frame->warm[component], band);
        float ambient = mixf(frame->ground_ambient[component], frame->sky_ambient[component], sky);
        float lit = albedo * (light * diffuse * shadow + ambient) + frame->rim_color[component] * rim;
        lit = mixf(lit, frame->cloud_color[component] * (light * diffuse + ambient * 1.6f), cloud * 0.8f);
        float specular_light = specular * light;
        float emission = emissive * frame->emissive_color[component];
        lit += specular_light + emission;
        float atmosphere = mixf(frame->atmosphere_dark[component], frame->atmosphere_lit[component], haze_mix) * haze_light;
        planet[component] = (lit * (1.0f - haze * 0.6f) + atmosphere * haze + glow[component]) * frame->exposure;
        bright_light[component] = (specular_light + emission - frame->bloom_threshold) * coverage;
    }
}

static inline __attribute__((always_inline)) void render_span(const Frame *frame, const Row *row, int start, int end, int with_planet, int with_halo)
{
#pragma omp simd
    for (int column = start; column < end; column++) {
        float sx = ((column + 0.5f) - frame->center) * frame->inverse_radius;
        float sy = row->sy;
        float distance_squared = sx * sx + sy * sy;
        float distance = sqrtf(distance_squared) + 1e-6f;
        float coverage = with_planet ? (with_halo ? clampf((1.0f - distance) * frame->radius + 0.5f, 0.0f, 1.0f) : 1.0f) : 0.0f;
        float glow[3];
        bloom_at(frame, row, column, glow);
        float planet[3] = {0.0f, 0.0f, 0.0f};
        float bright_light[3] = {0.0f, 0.0f, 0.0f};
        float halo[3] = {0.0f, 0.0f, 0.0f};
        float halo_alpha = 0.0f;
        if (with_planet) {
            shade_planet(frame, row, column, sx, sy, distance_squared, distance, coverage, glow, planet, bright_light);
        }
        if (with_halo) {
            shade_halo(frame, sx, sy, distance, glow, halo, &halo_alpha);
        }
        float halo_weight = halo_alpha * (1.0f - coverage);
        float inverse_halo = halo_alpha > 0.0f ? frame->exposure / fmaxf(halo_alpha, 1e-6f) : 0.0f;
        float alpha = coverage + halo_weight;
        float dither = frame->grain_amount * grain(column, row->row, frame->grain_seed) * alpha;
        float limit = alpha * 255.0f;
        uint32_t components[3];
        uint32_t bright_components[3];
        for (int component = 0; component < 3; component++) {
            float value = dither;
            if (with_planet) {
                value += graded(component, tone_map(planet[component])) * coverage;
            }
            if (with_halo) {
                value += graded(component, tone_map(halo[component] * inverse_halo)) * halo_weight;
            }
            components[component] = (uint32_t)clampf(value + 0.5f, 0.0f, limit);
            bright_components[component] = (uint32_t)clampf(bright_light[component] * BRIGHT_SCALE, 0.0f, 255.0f);
        }
        uint32_t pixel = pack((uint32_t)(alpha * 255.0f + 0.5f), components[0], components[1], components[2]);
        row->line[column] = alpha > 0.002f ? pixel : 0u;
        row->bright[column] = pack(0u, bright_components[0], bright_components[1], bright_components[2]);
    }
}

#if defined(__AVX2__) && defined(__FMA__)
typedef struct {
    __m256i top_left;
    __m256i top_right;
    __m256i bottom_left;
    __m256i bottom_right;
    __m256i weight_x;
    __m256i weight_y;
} Taps8;

static inline __m256 clamp8(__m256 value, float low, float high)
{
    return _mm256_min_ps(_mm256_max_ps(value, _mm256_set1_ps(low)), _mm256_set1_ps(high));
}

static inline __m256 smoothstep8(float edge0, float edge1, __m256 value)
{
    __m256 t = clamp8(_mm256_mul_ps(_mm256_sub_ps(value, _mm256_set1_ps(edge0)), _mm256_set1_ps(1.0f / (edge1 - edge0))), 0.0f, 1.0f);
    return _mm256_mul_ps(_mm256_mul_ps(t, t), _mm256_fnmadd_ps(_mm256_set1_ps(2.0f), t, _mm256_set1_ps(3.0f)));
}

static inline __m256 mix8(__m256 first, __m256 second, __m256 amount)
{
    return _mm256_fmadd_ps(_mm256_sub_ps(second, first), amount, first);
}

static inline __m256 byte8(__m256i pixel, int shift)
{
    return _mm256_cvtepi32_ps(_mm256_and_si256(_mm256_srli_epi32(pixel, shift), _mm256_set1_epi32(0xFF)));
}

static inline __m256i blend8(__m256i first, __m256i second, __m256i weight)
{
    __m256i mask = _mm256_set1_epi32(0x00FF00FF);
    __m256i weights = _mm256_or_si256(weight, _mm256_slli_epi32(weight, 16));
    __m256i inverse = _mm256_sub_epi16(_mm256_set1_epi16(256), weights);
    __m256i red_blue = _mm256_srli_epi16(_mm256_add_epi16(_mm256_mullo_epi16(_mm256_and_si256(first, mask), inverse),
                                                          _mm256_mullo_epi16(_mm256_and_si256(second, mask), weights)), 8);
    __m256i alpha_green = _mm256_andnot_si256(mask, _mm256_add_epi16(
        _mm256_mullo_epi16(_mm256_and_si256(_mm256_srli_epi32(first, 8), mask), inverse),
        _mm256_mullo_epi16(_mm256_and_si256(_mm256_srli_epi32(second, 8), mask), weights)));
    return _mm256_or_si256(red_blue, alpha_green);
}

static inline Taps8 taps8(const Frame *frame, __m256i level, __m256 u, __m256 v)
{
    Taps8 taps;
    __m256i one = _mm256_set1_epi32(1);
    __m256i width_shift = _mm256_sub_epi32(_mm256_set1_epi32(frame->width_shift), level);
    __m256i width_mask = _mm256_sub_epi32(_mm256_sllv_epi32(one, width_shift), one);
    __m256i last_row = _mm256_sub_epi32(_mm256_srlv_epi32(_mm256_set1_epi32(frame->base_height), level), one);
    __m256i remaining = _mm256_srlv_epi32(_mm256_set1_epi32(frame->texels), _mm256_add_epi32(level, level));
    __m256i offset = _mm256_cvtps_epi32(_mm256_mul_ps(_mm256_cvtepi32_ps(_mm256_sub_epi32(_mm256_set1_epi32(frame->texels), remaining)),
                                                      _mm256_set1_ps(4.0f / 3.0f)));
    __m256 scale = _mm256_castsi256_ps(_mm256_slli_epi32(_mm256_sub_epi32(_mm256_set1_epi32(127), level), 23));
    __m256 half = _mm256_set1_ps(0.5f);
    __m256 fu = _mm256_fmsub_ps(u, scale, half);
    __m256 fv = _mm256_min_ps(_mm256_max_ps(_mm256_fmsub_ps(v, scale, half), _mm256_setzero_ps()), _mm256_cvtepi32_ps(last_row));
    __m256i ix = _mm256_cvttps_epi32(_mm256_mul_ps(_mm256_add_ps(fu, _mm256_set1_ps(WRAP_BIAS_TEXELS)), _mm256_set1_ps(256.0f)));
    __m256i iy = _mm256_cvttps_epi32(_mm256_mul_ps(fv, _mm256_set1_ps(256.0f)));
    __m256i x0 = _mm256_and_si256(_mm256_srli_epi32(ix, 8), width_mask);
    __m256i x1 = _mm256_and_si256(_mm256_add_epi32(x0, one), width_mask);
    __m256i y0 = _mm256_srli_epi32(iy, 8);
    __m256i y1 = _mm256_min_epi32(_mm256_add_epi32(y0, one), last_row);
    __m256i top = _mm256_add_epi32(offset, _mm256_sllv_epi32(y0, width_shift));
    __m256i bottom = _mm256_add_epi32(offset, _mm256_sllv_epi32(y1, width_shift));
    taps.top_left = _mm256_add_epi32(top, x0);
    taps.top_right = _mm256_add_epi32(top, x1);
    taps.bottom_left = _mm256_add_epi32(bottom, x0);
    taps.bottom_right = _mm256_add_epi32(bottom, x1);
    taps.weight_x = _mm256_and_si256(ix, _mm256_set1_epi32(0xFF));
    taps.weight_y = _mm256_and_si256(iy, _mm256_set1_epi32(0xFF));
    return taps;
}

static inline __m256i gather8(const uint32_t *texels, __m256i index)
{
    return _mm256_i32gather_epi32((const int *)texels, index, 4);
}

static inline __m256i fetch8(const uint32_t *texels, const Taps8 *taps)
{
    return blend8(blend8(gather8(texels, taps->top_left), gather8(texels, taps->top_right), taps->weight_x),
                  blend8(gather8(texels, taps->bottom_left), gather8(texels, taps->bottom_right), taps->weight_x), taps->weight_y);
}

static inline __m256 tone_map8(__m256 value)
{
    value = _mm256_max_ps(value, _mm256_setzero_ps());
    __m256 numerator = _mm256_mul_ps(value, _mm256_fmadd_ps(value, _mm256_set1_ps(2.51f), _mm256_set1_ps(0.03f)));
    __m256 denominator = _mm256_fmadd_ps(value, _mm256_fmadd_ps(value, _mm256_set1_ps(2.43f), _mm256_set1_ps(0.59f)), _mm256_set1_ps(0.14f));
    return _mm256_min_ps(_mm256_div_ps(numerator, denominator), _mm256_set1_ps(1.0f));
}

static inline __m256 dot8(__m256 x, __m256 y, __m256 z, float dx, float dy, float dz)
{
    return _mm256_fmadd_ps(x, _mm256_set1_ps(dx), _mm256_fmadd_ps(y, _mm256_set1_ps(dy), _mm256_mul_ps(z, _mm256_set1_ps(dz))));
}

static void render_interior(const Frame *frame, const Row *row, int start, int end)
{
    const __m256 zero = _mm256_setzero_ps(), one = _mm256_set1_ps(1.0f);
    const __m256i last_level = _mm256_set1_epi32(frame->last_level);
    const __m256 lanes = _mm256_setr_ps(0.5f, 1.5f, 2.5f, 3.5f, 4.5f, 5.5f, 6.5f, 7.5f);
    const __m256i lane_offsets = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
    const __m256 sy = _mm256_set1_ps(row->sy);
    const __m256 cos_pitch = _mm256_set1_ps(frame->cos_pitch), sin_pitch = _mm256_set1_ps(frame->sin_pitch);
    const __m256 inverse_255 = _mm256_set1_ps(1.0f / 255.0f), inverse_256 = _mm256_set1_ps(1.0f / 256.0f);
    int column = start;
    for (; column + 8 <= end; column += 8) {
        __m256 sx = _mm256_mul_ps(_mm256_sub_ps(_mm256_add_ps(_mm256_set1_ps((float)column), lanes), _mm256_set1_ps(frame->center)),
                                  _mm256_set1_ps(frame->inverse_radius));
        __m256 distance_squared = _mm256_fmadd_ps(sx, sx, _mm256_mul_ps(sy, sy));
        __m256 sz = _mm256_sqrt_ps(_mm256_max_ps(_mm256_sub_ps(one, distance_squared), zero));

        __m256 base_u = _mm256_loadu_ps(row->u + column);
        __m256 pixel_u = _mm256_add_ps(base_u, _mm256_set1_ps(frame->shift));
        __m256 pixel_v = _mm256_loadu_ps(row->v + column);
        __m256 pixel_lod = _mm256_loadu_ps(row->lod + column);
        __m256i level = _mm256_min_epi32(_mm256_cvttps_epi32(pixel_lod), last_level);
        __m256i next_level = _mm256_min_epi32(_mm256_add_epi32(level, _mm256_set1_epi32(1)), last_level);
        __m256i mip_weight = _mm256_cvttps_epi32(_mm256_mul_ps(clamp8(_mm256_sub_ps(pixel_lod, _mm256_cvtepi32_ps(level)), 0.0f, 1.0f),
                                                               _mm256_set1_ps(256.0f)));
        Taps8 taps = taps8(frame, level, pixel_u, pixel_v);
        __m256i color = fetch8(frame->color_source, &taps);
        __m256i surface = fetch8(frame->surface_source, &taps);
        taps = taps8(frame, next_level, pixel_u, pixel_v);
        color = blend8(color, fetch8(frame->color_source, &taps), mip_weight);
        surface = blend8(surface, fetch8(frame->surface_source, &taps), mip_weight);
        __m256 texture_height = _mm256_set1_ps(frame->texture_height);
        __m256 pole_distance = _mm256_min_ps(pixel_v, _mm256_sub_ps(texture_height, pixel_v));
        __m256i pole_weight = _mm256_cvttps_epi32(_mm256_mul_ps(clamp8(_mm256_fnmadd_ps(pole_distance, _mm256_set1_ps(1.0f / POLE_TEXELS), one), 0.0f, 1.0f),
                                                                _mm256_set1_ps(256.0f)));
        __m256i north = _mm256_castps_si256(_mm256_cmp_ps(pixel_v, _mm256_mul_ps(texture_height, _mm256_set1_ps(0.5f)), _CMP_LT_OQ));
        color = blend8(color, _mm256_blendv_epi8(_mm256_set1_epi32((int)frame->color_poles[1]), _mm256_set1_epi32((int)frame->color_poles[0]), north), pole_weight);
        surface = blend8(surface, _mm256_blendv_epi8(_mm256_set1_epi32((int)frame->surface_poles[1]), _mm256_set1_epi32((int)frame->surface_poles[0]), north), pole_weight);

        __m256i cloud_level = _mm256_min_epi32(_mm256_cvttps_epi32(_mm256_add_ps(pixel_lod, _mm256_set1_ps(1.5f))), last_level);
        taps = taps8(frame, cloud_level, _mm256_add_ps(base_u, _mm256_set1_ps(frame->cloud_shift)), pixel_v);
        __m256 cloud_top_left = _mm256_mul_ps(byte8(gather8(frame->surface_source, taps.top_left), 24), inverse_255);
        __m256 cloud_top_right = _mm256_mul_ps(byte8(gather8(frame->surface_source, taps.top_right), 24), inverse_255);
        __m256 cloud_bottom_left = _mm256_mul_ps(byte8(gather8(frame->surface_source, taps.bottom_left), 24), inverse_255);
        __m256 cloud_bottom_right = _mm256_mul_ps(byte8(gather8(frame->surface_source, taps.bottom_right), 24), inverse_255);
        __m256 cloud_x = _mm256_mul_ps(_mm256_cvtepi32_ps(taps.weight_x), inverse_256);
        __m256 cloud_y = _mm256_mul_ps(_mm256_cvtepi32_ps(taps.weight_y), inverse_256);
        __m256 cloud = mix8(mix8(cloud_top_left, cloud_top_right, cloud_x), mix8(cloud_bottom_left, cloud_bottom_right, cloud_x), cloud_y);
        __m256 shadow_x = clamp8(_mm256_sub_ps(cloud_x, _mm256_set1_ps(frame->shadow_shift_x)), 0.0f, 1.0f);
        __m256 shadow_y = clamp8(_mm256_add_ps(cloud_y, _mm256_set1_ps(frame->shadow_shift_y)), 0.0f, 1.0f);
        __m256 cloud_shadow = mix8(mix8(cloud_top_left, cloud_top_right, shadow_x), mix8(cloud_bottom_left, cloud_bottom_right, shadow_x), shadow_y);

        __m256 world_y = _mm256_fmadd_ps(sy, cos_pitch, _mm256_mul_ps(sz, sin_pitch));
        __m256 world_z = _mm256_fmsub_ps(sz, cos_pitch, _mm256_mul_ps(sy, sin_pitch));
        __m256 latitude_cos = _mm256_sqrt_ps(_mm256_fmadd_ps(sx, sx, _mm256_mul_ps(world_z, world_z)));
        __m256 inverse_cos = _mm256_div_ps(one, _mm256_max_ps(latitude_cos, _mm256_set1_ps(1e-4f)));
        __m256 east_x = _mm256_mul_ps(world_z, inverse_cos);
        __m256 east_world_z = _mm256_mul_ps(_mm256_sub_ps(zero, sx), inverse_cos);
        __m256 east_y = _mm256_mul_ps(_mm256_sub_ps(zero, east_world_z), sin_pitch);
        __m256 east_z = _mm256_mul_ps(east_world_z, cos_pitch);
        __m256 north_x = _mm256_mul_ps(_mm256_mul_ps(_mm256_sub_ps(zero, world_y), sx), inverse_cos);
        __m256 north_world_z = _mm256_mul_ps(_mm256_mul_ps(_mm256_sub_ps(zero, world_y), world_z), inverse_cos);
        __m256 north_y = _mm256_fnmadd_ps(north_world_z, sin_pitch, _mm256_mul_ps(latitude_cos, cos_pitch));
        __m256 north_z = _mm256_fmadd_ps(north_world_z, cos_pitch, _mm256_mul_ps(latitude_cos, sin_pitch));
        __m256 bump = _mm256_set1_ps(frame->bump);
        __m256 slope_east = _mm256_mul_ps(_mm256_sub_ps(byte8(surface, 16), _mm256_set1_ps(128.0f)), bump);
        __m256 slope_north = _mm256_mul_ps(_mm256_sub_ps(byte8(surface, 8), _mm256_set1_ps(128.0f)), bump);
        __m256 inverse_length = _mm256_div_ps(one, _mm256_sqrt_ps(_mm256_fmadd_ps(slope_east, slope_east, _mm256_fmadd_ps(slope_north, slope_north, one))));
        __m256 bumped_x = _mm256_mul_ps(_mm256_fnmadd_ps(slope_north, north_x, _mm256_fnmadd_ps(slope_east, east_x, sx)), inverse_length);
        __m256 bumped_y = _mm256_mul_ps(_mm256_fnmadd_ps(slope_north, north_y, _mm256_fnmadd_ps(slope_east, east_y, sy)), inverse_length);
        __m256 bumped_z = _mm256_mul_ps(_mm256_fnmadd_ps(slope_north, north_z, _mm256_fnmadd_ps(slope_east, east_z, sz)), inverse_length);

        __m256 geometric = dot8(sx, sy, sz, frame->light_x, frame->light_y, frame->light_z);
        __m256 facing = dot8(bumped_x, bumped_y, bumped_z, frame->light_x, frame->light_y, frame->light_z);
        __m256 diffuse = _mm256_mul_ps(clamp8(_mm256_mul_ps(_mm256_add_ps(facing, _mm256_set1_ps(0.3f)), _mm256_set1_ps(1.0f / 1.3f)), 0.0f, 1.0f),
                                       smoothstep8(-0.3f, 0.15f, geometric));
        __m256 daylight = smoothstep8(-0.12f, 0.32f, geometric);
        __m256 band_distance = _mm256_mul_ps(_mm256_sub_ps(geometric, _mm256_set1_ps(0.03f)), _mm256_set1_ps(1.0f / 0.24f));
        __m256 band = _mm256_mul_ps(_mm256_set1_ps(frame->warm_amount), clamp8(_mm256_fnmadd_ps(band_distance, band_distance, one), 0.0f, 1.0f));
        __m256 rim = clamp8(dot8(bumped_x, bumped_y, bumped_z, frame->rim_x, frame->rim_y, frame->rim_z), 0.0f, 1.0f);
        __m256 sky = _mm256_fmadd_ps(bumped_y, _mm256_set1_ps(0.5f), _mm256_set1_ps(0.5f));
        __m256 half_facing = clamp8(dot8(bumped_x, bumped_y, bumped_z, frame->half_x, frame->half_y, frame->half_z), 0.0f, 1.0f);
        half_facing = _mm256_and_ps(half_facing, _mm256_cmp_ps(half_facing, _mm256_set1_ps(0.3f), _CMP_GT_OQ));
        __m256 broad = _mm256_mul_ps(half_facing, half_facing);
        broad = _mm256_mul_ps(broad, broad);
        broad = _mm256_mul_ps(broad, broad);
        __m256 glossy = _mm256_mul_ps(broad, broad);
        glossy = _mm256_mul_ps(glossy, glossy);
        glossy = _mm256_mul_ps(glossy, glossy);
        __m256 grazing = _mm256_sub_ps(one, sz);
        __m256 grazing_squared = _mm256_mul_ps(grazing, grazing);
        __m256 fresnel = _mm256_fmadd_ps(_mm256_mul_ps(_mm256_mul_ps(grazing_squared, grazing_squared), grazing), _mm256_set1_ps(0.96f), _mm256_set1_ps(0.04f));
        __m256 specular = _mm256_mul_ps(_mm256_mul_ps(byte8(surface, 0), inverse_255), _mm256_sub_ps(one, cloud));
        specular = _mm256_mul_ps(specular, _mm256_fmadd_ps(broad, _mm256_set1_ps(0.03f), glossy));
        specular = _mm256_mul_ps(_mm256_mul_ps(specular, _mm256_fmadd_ps(fresnel, _mm256_set1_ps(4.0f), one)), daylight);
        __m256 shadow = _mm256_fnmadd_ps(_mm256_mul_ps(_mm256_set1_ps(0.45f), cloud_shadow), daylight, one);
        __m256 emissive = _mm256_mul_ps(byte8(color, 24), inverse_255);
        __m256 night = _mm256_sub_ps(one, daylight);
        emissive = _mm256_mul_ps(_mm256_mul_ps(emissive, emissive), _mm256_mul_ps(_mm256_mul_ps(night, night), _mm256_fnmadd_ps(_mm256_set1_ps(0.6f), cloud, one)));
        __m256 haze = _mm256_mul_ps(grazing_squared, _mm256_fmadd_ps(grazing, _mm256_set1_ps(0.25f), _mm256_set1_ps(0.35f)));
        __m256 haze_light = _mm256_fmadd_ps(clamp8(_mm256_add_ps(geometric, _mm256_set1_ps(0.25f)), 0.0f, 1.0f), _mm256_set1_ps(1.1f), _mm256_set1_ps(0.25f));
        __m256 haze_mix = smoothstep8(-0.35f, 0.5f, geometric);
        __m256 haze_keep = _mm256_fnmadd_ps(haze, _mm256_set1_ps(0.6f), one);
        __m256 cloud_amount = _mm256_mul_ps(cloud, _mm256_set1_ps(0.8f));
        __m256 lit_light = _mm256_mul_ps(diffuse, shadow);

        __m256i column_index = _mm256_add_epi32(_mm256_set1_epi32(column), lane_offsets);
        __m256i hash = _mm256_xor_si256(_mm256_xor_si256(_mm256_mullo_epi32(column_index, _mm256_set1_epi32((int)0x8da6b343u)),
                                                         _mm256_set1_epi32((int)((uint32_t)row->row * 0xd8163841u))),
                                        _mm256_set1_epi32((int)frame->grain_seed));
        hash = _mm256_xor_si256(hash, _mm256_srli_epi32(hash, 15));
        hash = _mm256_mullo_epi32(hash, _mm256_set1_epi32(0x2c1b3c6d));
        hash = _mm256_xor_si256(hash, _mm256_srli_epi32(hash, 12));
        __m256 dither = _mm256_mul_ps(_mm256_fmsub_ps(_mm256_cvtepi32_ps(_mm256_and_si256(hash, _mm256_set1_epi32(0xFFFF))),
                                                      _mm256_set1_ps(1.0f / 32767.5f), one), _mm256_set1_ps(frame->grain_amount));

        __m256i bloom_left = _mm256_cvttps_epi32(_mm256_floor_ps(_mm256_fmsub_ps(_mm256_cvtepi32_ps(column_index), _mm256_set1_ps(0.25f), _mm256_set1_ps(0.375f))));
        __m256 bloom_weight = _mm256_sub_ps(_mm256_fmsub_ps(_mm256_cvtepi32_ps(column_index), _mm256_set1_ps(0.25f), _mm256_set1_ps(0.375f)), _mm256_cvtepi32_ps(bloom_left));
        __m256i bloom_right = _mm256_min_epi32(_mm256_add_epi32(bloom_left, _mm256_set1_epi32(1)), _mm256_set1_epi32(frame->quarter - 1));
        bloom_left = _mm256_max_epi32(bloom_left, _mm256_setzero_si256());
        bloom_left = _mm256_add_epi32(bloom_left, _mm256_add_epi32(bloom_left, bloom_left));
        bloom_right = _mm256_add_epi32(bloom_right, _mm256_add_epi32(bloom_right, bloom_right));

        __m256i packed = _mm256_set1_epi32((int)0xFF000000u);
        __m256i bright_packed = _mm256_setzero_si256();
        for (int component = 0; component < 3; component++) {
            int shift = 16 - 8 * component;
            __m256i offset = _mm256_set1_epi32(component);
            __m256 glow = mix8(_mm256_i32gather_ps(row->glow, _mm256_add_epi32(bloom_left, offset), 4),
                               _mm256_i32gather_ps(row->glow, _mm256_add_epi32(bloom_right, offset), 4), bloom_weight);
            __m256 encoded = _mm256_mul_ps(byte8(color, shift), inverse_255);
            __m256 albedo = _mm256_mul_ps(encoded, _mm256_fmadd_ps(encoded, _mm256_fmadd_ps(encoded, _mm256_set1_ps(0.305306011f), _mm256_set1_ps(0.682171111f)),
                                                                   _mm256_set1_ps(0.012522878f)));
            __m256 light = mix8(_mm256_set1_ps(frame->key[component]), _mm256_set1_ps(frame->warm[component]), band);
            __m256 ambient = mix8(_mm256_set1_ps(frame->ground_ambient[component]), _mm256_set1_ps(frame->sky_ambient[component]), sky);
            __m256 lit = _mm256_fmadd_ps(albedo, _mm256_fmadd_ps(light, lit_light, ambient), _mm256_mul_ps(_mm256_set1_ps(frame->rim_color[component]), rim));
            __m256 cloud_lit = _mm256_mul_ps(_mm256_set1_ps(frame->cloud_color[component]), _mm256_fmadd_ps(light, diffuse, _mm256_mul_ps(ambient, _mm256_set1_ps(1.6f))));
            lit = mix8(lit, cloud_lit, cloud_amount);
            __m256 specular_light = _mm256_mul_ps(specular, light);
            __m256 emission = _mm256_mul_ps(emissive, _mm256_set1_ps(frame->emissive_color[component]));
            lit = _mm256_add_ps(lit, _mm256_add_ps(specular_light, emission));
            __m256 atmosphere = _mm256_mul_ps(mix8(_mm256_set1_ps(frame->atmosphere_dark[component]), _mm256_set1_ps(frame->atmosphere_lit[component]), haze_mix), haze_light);
            __m256 planet = _mm256_mul_ps(_mm256_add_ps(_mm256_fmadd_ps(lit, haze_keep, _mm256_mul_ps(atmosphere, haze)), glow), _mm256_set1_ps(frame->exposure));
            __m256i grade_index = _mm256_cvttps_epi32(_mm256_mul_ps(tone_map8(planet), _mm256_set1_ps((float)GRADE_STEPS)));
            __m256 value = _mm256_add_ps(_mm256_i32gather_ps(grade_table[component], grade_index, 4), dither);
            __m256i channel_value = _mm256_cvttps_epi32(clamp8(_mm256_add_ps(value, _mm256_set1_ps(0.5f)), 0.0f, 255.0f));
            packed = _mm256_or_si256(packed, _mm256_slli_epi32(channel_value, shift));
            __m256 bright_value = _mm256_sub_ps(_mm256_add_ps(specular_light, emission), _mm256_set1_ps(frame->bloom_threshold));
            __m256i bright_channel = _mm256_cvttps_epi32(clamp8(_mm256_mul_ps(bright_value, _mm256_set1_ps(BRIGHT_SCALE)), 0.0f, 255.0f));
            bright_packed = _mm256_or_si256(bright_packed, _mm256_slli_epi32(bright_channel, shift));
        }
        _mm256_storeu_si256((__m256i *)(row->line + column), packed);
        _mm256_storeu_si256((__m256i *)(row->bright + column), bright_packed);
    }
    render_span(frame, row, column, end, 1, 0);
}
#else
static void render_interior(const Frame *frame, const Row *row, int start, int end)
{
    render_span(frame, row, start, end, 1, 0);
}
#endif

static int clamp_column(int column, int low, int high)
{
    return column < low ? low : (column > high ? high : column);
}

static float half_chord(float extent, float sy, float radius)
{
    float squared = extent * extent - sy * sy;
    return squared > 0.0f ? sqrtf(squared) * radius : -1.0f;
}

void globe_render(const GlobeParams *params, const float *u, const float *v, const float *lod, int size, float radius,
                  uint32_t *output, int output_stride, uint32_t *bright, float *bloom_accumulator, float *bloom_scratch, float *bloom)
{
    Frame frame;
    float pitch = params->pitch_degrees * (float)M_PI / 180.0f;
    frame.color_source = color_texels;
    frame.surface_source = surface_texels;
    for (int pole = 0; pole < 2; pole++) {
        frame.color_poles[pole] = color_poles[pole];
        frame.surface_poles[pole] = surface_poles[pole];
    }
    frame.cos_pitch = cosf(pitch);
    frame.sin_pitch = sinf(pitch);
    frame.light_x = params->light[0];
    frame.light_y = params->light[1];
    frame.light_z = params->light[2];
    float half_x = frame.light_x, half_y = frame.light_y, half_z = frame.light_z + 1.0f;
    float half_length = sqrtf(half_x * half_x + half_y * half_y + half_z * half_z);
    half_length = half_length > 1e-6f ? half_length : 1.0f;
    frame.half_x = half_x / half_length;
    frame.half_y = half_y / half_length;
    frame.half_z = half_z / half_length;
    frame.rim_x = -0.3f * frame.light_x;
    frame.rim_y = 0.35f;
    frame.rim_z = -0.88f;
    frame.planar_length = sqrtf(frame.light_x * frame.light_x + frame.light_y * frame.light_y);
    frame.planar_x = frame.planar_length > 1e-4f ? frame.light_x / frame.planar_length : 0.0f;
    frame.planar_y = frame.planar_length > 1e-4f ? frame.light_y / frame.planar_length : 0.0f;
    frame.backlight = frame.light_z < 0.0f ? -frame.light_z : 0.0f;
    for (int component = 0; component < 3; component++) {
        frame.key[component] = params->key_color[component];
        frame.warm[component] = params->warm_color[component] * 1.4f;
        frame.rim_color[component] = params->rim_color[component] * 0.35f;
        frame.sky_ambient[component] = params->sky_ambient[component];
        frame.ground_ambient[component] = params->ground_ambient[component];
        frame.atmosphere_lit[component] = params->atmosphere_lit[component];
        frame.atmosphere_dark[component] = params->atmosphere_dark[component];
        frame.emissive_color[component] = params->emissive_color[component];
        frame.cloud_color[component] = params->cloud_color[component];
    }
    frame.warm_amount = params->warm_amount;
    frame.bump = params->bump / 127.0f;
    frame.exposure = params->exposure;
    frame.shift = params->shift;
    frame.cloud_shift = params->cloud_shift;
    frame.bloom_threshold = params->bloom_threshold;
    frame.bloom_strength = params->bloom_strength;
    frame.grain_amount = params->grain_amount;
    frame.grain_seed = params->grain_seed;
    frame.center = size / 2.0f;
    frame.radius = radius;
    frame.inverse_radius = 1.0f / radius;
    frame.aberration = 0.5f * frame.inverse_radius;
    frame.shadow_shift_x = frame.light_x * SHADOW_TEXELS;
    frame.shadow_shift_y = frame.light_y * SHADOW_TEXELS;
    frame.texture_height = (float)geometry.heights[0];
    frame.last_level = geometry.count - 1;
    frame.quarter = (size + 3) / 4;
    frame.width_shift = __builtin_ctz((unsigned)geometry.widths[0]);
    frame.base_height = geometry.heights[0];
    frame.texels = geometry.widths[0] * geometry.heights[0];
    float halo_extent = params->halo_extent;
    float edge = 1.0f / radius;

#pragma omp parallel for schedule(dynamic, 8)
    for (int row_index = 0; row_index < size; row_index++) {
        Row row;
        row.row = row_index;
        row.line = (uint32_t *)((uint8_t *)output + (size_t)row_index * output_stride);
        row.bright = bright + (size_t)row_index * size;
        row.u = u + (size_t)row_index * size;
        row.v = v + (size_t)row_index * size;
        row.lod = lod + (size_t)row_index * size;
        row.sy = (frame.center - (row_index + 0.5f)) * frame.inverse_radius;
        float bloom_y = (row_index + 0.5f) * 0.25f - 0.5f;
        int upper = (int)floorf(bloom_y);
        float bloom_weight_y = bloom_y - (float)upper;
        int lower = upper + 1 >= frame.quarter ? frame.quarter - 1 : upper + 1;
        upper = upper < 0 ? 0 : upper;
        const float *bloom_upper = bloom + (size_t)upper * frame.quarter * 3;
        const float *bloom_lower = bloom + (size_t)lower * frame.quarter * 3;
        float glow[frame.quarter * 3];
        for (int index = 0; index < frame.quarter * 3; index++) {
            glow[index] = mixf(bloom_upper[index], bloom_lower[index], bloom_weight_y) * frame.bloom_strength;
        }
        row.glow = glow;

        float center = frame.center - 0.5f;
        float halo_half = half_chord(halo_extent, row.sy, radius);
        float outer_half = half_chord(1.0f + edge, row.sy, radius);
        float inner_half = half_chord(1.0f - edge, row.sy, radius);
        int start = halo_half < 0.0f ? size : clamp_column((int)floorf(center - halo_half), 0, size);
        int end = halo_half < 0.0f ? size : clamp_column((int)ceilf(center + halo_half) + 1, start, size);
        int outer_left = outer_half < 0.0f ? end : clamp_column((int)floorf(center - outer_half), start, end);
        int outer_right = outer_half < 0.0f ? end : clamp_column((int)ceilf(center + outer_half) + 1, outer_left, end);
        int inner_left = inner_half < 0.0f ? outer_left : clamp_column((int)ceilf(center - inner_half), outer_left, outer_right);
        int inner_right = inner_half < 0.0f ? outer_left : clamp_column((int)floorf(center + inner_half) + 1, inner_left, outer_right);
        memset(row.line, 0, sizeof(uint32_t) * (size_t)start);
        memset(row.line + end, 0, sizeof(uint32_t) * (size_t)(size - end));
        memset(row.bright, 0, sizeof(uint32_t) * (size_t)start);
        memset(row.bright + end, 0, sizeof(uint32_t) * (size_t)(size - end));
        render_span(&frame, &row, start, outer_left, 0, 1);
        render_span(&frame, &row, outer_left, inner_left, 1, 1);
        render_interior(&frame, &row, inner_left, inner_right);
        render_span(&frame, &row, inner_right, outer_right, 1, 1);
        render_span(&frame, &row, outer_right, end, 0, 1);
    }
    downsample_bright(bright, size, bloom_accumulator, frame.quarter);
    blur_horizontal(bloom_accumulator, bloom_scratch, frame.quarter);
    blur_vertical(bloom_scratch, bloom, frame.quarter);
}

static inline uint32_t lattice_hash(int x, int y, int z, uint32_t seed)
{
    uint32_t hash = seed ^ (uint32_t)x * 0x8da6b343u ^ (uint32_t)y * 0xd8163841u ^ (uint32_t)z * 0xcb1ab31fu;
    hash ^= hash >> 13;
    hash *= 0x5bd1e995u;
    hash ^= hash >> 15;
    return hash;
}

static inline float lattice_value(int x, int y, int z, uint32_t seed)
{
    return (float)(lattice_hash(x, y, z, seed) & 0xFFFFFFu) / 16777215.0f;
}

static inline float fade(float t)
{
    return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
}

static float value_noise(float x, float y, float z, uint32_t seed)
{
    float fx = floorf(x), fy = floorf(y), fz = floorf(z);
    int ix = (int)fx, iy = (int)fy, iz = (int)fz;
    float tx = fade(x - fx), ty = fade(y - fy), tz = fade(z - fz);
    float c000 = lattice_value(ix, iy, iz, seed), c100 = lattice_value(ix + 1, iy, iz, seed);
    float c010 = lattice_value(ix, iy + 1, iz, seed), c110 = lattice_value(ix + 1, iy + 1, iz, seed);
    float c001 = lattice_value(ix, iy, iz + 1, seed), c101 = lattice_value(ix + 1, iy, iz + 1, seed);
    float c011 = lattice_value(ix, iy + 1, iz + 1, seed), c111 = lattice_value(ix + 1, iy + 1, iz + 1, seed);
    return mixf(mixf(mixf(c000, c100, tx), mixf(c010, c110, tx), ty), mixf(mixf(c001, c101, tx), mixf(c011, c111, tx), ty), tz);
}

static float fbm(float x, float y, float z, int octaves, uint32_t seed)
{
    float sum = 0.0f, amplitude = 0.5f, total = 0.0f;
    for (int octave = 0; octave < octaves; octave++) {
        sum += value_noise(x, y, z, seed + (uint32_t)octave * 0x9e3779b9u) * amplitude;
        total += amplitude;
        amplitude *= 0.5f;
        x = x * 2.03f + 17.1f;
        y = y * 2.03f - 9.7f;
        z = z * 2.03f + 4.3f;
    }
    return sum / total;
}

static void distance_to_outside(const uint8_t *inside, int width, int height, int padding, float *distance)
{
    int padded = width + 2 * padding;
    const float diagonal = 1.41421356f;
    for (int row = 0; row < height; row++) {
        for (int column = 0; column < padded; column++) {
            int source = ((column - padding) % width + width) % width;
            distance[(size_t)row * padded + column] = inside[(size_t)row * width + source] ? DISTANCE_CAP : 0.0f;
        }
    }
    for (int row = 0; row < height; row++) {
        float *line = distance + (size_t)row * padded;
        float *above = row > 0 ? line - padded : NULL;
        for (int column = 0; column < padded; column++) {
            float best = line[column];
            if (column > 0) {
                best = fminf(best, line[column - 1] + 1.0f);
            }
            if (above) {
                best = fminf(best, above[column] + 1.0f);
                if (column > 0) {
                    best = fminf(best, above[column - 1] + diagonal);
                }
                if (column + 1 < padded) {
                    best = fminf(best, above[column + 1] + diagonal);
                }
            }
            line[column] = best;
        }
    }
    for (int row = height - 1; row >= 0; row--) {
        float *line = distance + (size_t)row * padded;
        float *below = row + 1 < height ? line + padded : NULL;
        for (int column = padded - 1; column >= 0; column--) {
            float best = line[column];
            if (column + 1 < padded) {
                best = fminf(best, line[column + 1] + 1.0f);
            }
            if (below) {
                best = fminf(best, below[column] + 1.0f);
                if (column > 0) {
                    best = fminf(best, below[column - 1] + diagonal);
                }
                if (column + 1 < padded) {
                    best = fminf(best, below[column + 1] + diagonal);
                }
            }
            line[column] = best;
        }
    }
}

int globe_bake(const uint8_t *land, int land_stride, const uint32_t *coast, int coast_stride, const uint8_t *lights, int lights_stride,
               int source_width, int source_height, const BakeParams *params, uint32_t *color_out, uint32_t *surface_out, int width, int height)
{
    int factor = source_width / width;
    if (factor < 1 || source_height / height != factor) {
        return -1;
    }
    size_t count = (size_t)width * height;
    int padding = (int)DISTANCE_CAP + 1;
    int padded = width + 2 * padding;
    float *coverage = malloc(count * sizeof(float));
    float *heights = malloc(count * sizeof(float));
    float *land_distance = malloc((size_t)padded * height * sizeof(float));
    float *ocean_distance = malloc((size_t)padded * height * sizeof(float));
    uint8_t *is_land = calloc(count, 1);
    uint8_t *is_ocean = calloc(count, 1);
    if (!coverage || !heights || !land_distance || !ocean_distance || !is_land || !is_ocean) {
        free(coverage);
        free(heights);
        free(land_distance);
        free(ocean_distance);
        free(is_land);
        free(is_ocean);
        return -2;
    }
    float block_area = (float)(factor * factor);

#pragma omp parallel for schedule(static)
    for (int row = 0; row < height; row++) {
        for (int column = 0; column < width; column++) {
            uint32_t sum = 0;
            for (int y = 0; y < factor; y++) {
                const uint8_t *source = land + (size_t)(row * factor + y) * land_stride + (size_t)column * factor;
                for (int x = 0; x < factor; x++) {
                    sum += source[x];
                }
            }
            size_t index = (size_t)row * width + column;
            coverage[index] = sum / (255.0f * block_area);
            is_land[index] = coverage[index] >= 0.5f;
            is_ocean[index] = !is_land[index];
        }
    }
    distance_to_outside(is_land, width, height, padding, land_distance);
    distance_to_outside(is_ocean, width, height, padding, ocean_distance);

    uint32_t seed = params->seed;
#pragma omp parallel for schedule(static)
    for (int row = 0; row < height; row++) {
        float latitude = (0.5f - (row + 0.5f) / height) * (float)M_PI;
        for (int column = 0; column < width; column++) {
            float longitude = ((column + 0.5f) / width - 0.5f) * 2.0f * (float)M_PI;
            float px = cosf(latitude) * cosf(longitude), py = sinf(latitude), pz = cosf(latitude) * sinf(longitude);
            size_t index = (size_t)row * width + column;
            size_t padded_index = (size_t)row * padded + column + padding;
            float inland = land_distance[padded_index];
            float offshore = ocean_distance[padded_index];
            float relief = fbm(px * 6.0f, py * 6.0f, pz * 6.0f, 6, seed);
            float ridges = 1.0f - fabsf(fbm(px * 11.0f, py * 11.0f, pz * 11.0f, 5, seed + 101u) * 2.0f - 1.0f);
            float land_height = 0.12f + 0.4f * smoothstepf(0.0f, 36.0f, inland) * (0.35f + 0.65f * ridges * relief * 1.4f) + 0.1f * relief;
            float ocean_height = -0.05f * smoothstepf(0.0f, 30.0f, offshore) + 0.02f * relief;
            heights[index] = mixf(ocean_height, land_height, coverage[index]);
        }
    }

#pragma omp parallel for schedule(static)
    for (int row = 0; row < height; row++) {
        float latitude = (0.5f - (row + 0.5f) / height) * (float)M_PI;
        float latitude_cos = cosf(latitude);
        float east_scale = 1.0f / (latitude_cos > 0.35f ? latitude_cos : 0.35f);
        int row_above = row > 0 ? row - 1 : 0;
        int row_below = row + 1 < height ? row + 1 : height - 1;
        for (int column = 0; column < width; column++) {
            size_t index = (size_t)row * width + column;
            size_t padded_index = (size_t)row * padded + column + padding;
            float longitude = ((column + 0.5f) / width - 0.5f) * 2.0f * (float)M_PI;
            float px = latitude_cos * cosf(longitude), py = sinf(latitude), pz = latitude_cos * sinf(longitude);
            int left = (column - 1 + width) % width, right = (column + 1) % width;
            float slope_east = (heights[(size_t)row * width + right] - heights[(size_t)row * width + left]) * 0.5f * east_scale * 22.0f;
            float slope_north = (heights[(size_t)row_above * width + column] - heights[(size_t)row_below * width + column]) * 0.5f * 22.0f;
            float land_amount = coverage[index];
            float inland = land_distance[padded_index];
            float offshore = ocean_distance[padded_index];
            float variation = fbm(px * 14.0f, py * 14.0f, pz * 14.0f, 5, seed + 211u);
            float tint = fbm(px * 3.0f, py * 3.0f, pz * 3.0f, 3, seed + 307u);
            float warp = fbm(px * 2.0f, py * 2.0f, pz * 2.0f, 3, seed + 401u) * 1.6f;
            float cloud_noise = fbm(px * 3.2f + warp, py * 5.5f - warp, pz * 3.2f + warp, 6, seed + 503u);
            float cloud = smoothstepf(0.56f, 0.8f, cloud_noise) * (0.5f + 0.4f * smoothstepf(0.0f, 0.35f, fabsf(py)));
            float shelf = 1.0f - smoothstepf(0.0f, 26.0f, offshore);
            float elevation = smoothstepf(4.0f, 60.0f, inland) * (0.6f + 0.4f * variation);

            float albedo[3];
            const uint32_t *coast_block = coast + (size_t)(row * factor) * (coast_stride / 4) + (size_t)column * factor;
            float coast_sum[4] = {0.0f, 0.0f, 0.0f, 0.0f};
            uint32_t light_sum = 0;
            for (int y = 0; y < factor; y++) {
                const uint32_t *coast_row = coast_block + (size_t)y * (coast_stride / 4);
                const uint8_t *light_row = lights + (size_t)(row * factor + y) * lights_stride + (size_t)column * factor;
                for (int x = 0; x < factor; x++) {
                    for (int component = 0; component < 4; component++) {
                        coast_sum[component] += (float)channel(coast_row[x], 24 - 8 * component);
                    }
                    light_sum += light_row[x];
                }
            }
            float coast_alpha = coast_sum[0] / (255.0f * block_area);
            for (int component = 0; component < 3; component++) {
                float ocean = mixf(params->ocean_deep[component], params->ocean_shelf[component], shelf) * (0.9f + 0.2f * tint);
                float ground = mixf(params->land_low[component], params->land_high[component], elevation) * (0.82f + 0.36f * variation);
                float base = mixf(ocean, ground, land_amount);
                albedo[component] = coast_sum[component + 1] / (255.0f * block_area) + base * (1.0f - coast_alpha);
            }
            float emission = clampf(light_sum / (255.0f * block_area) * params->lights_gain, 0.0f, 1.0f);
            float specular = mixf(1.0f, 0.06f, land_amount);
            color_out[index] = pack(to_byte(sqrtf(emission)), to_byte(albedo[0]), to_byte(albedo[1]), to_byte(albedo[2]));
            surface_out[index] = pack(to_byte(cloud), to_byte(0.5f + 0.5f * clampf(slope_east, -1.0f, 1.0f)),
                                      to_byte(0.5f + 0.5f * clampf(slope_north, -1.0f, 1.0f)), to_byte(specular));
        }
    }
    free(coverage);
    free(heights);
    free(land_distance);
    free(ocean_distance);
    free(is_land);
    free(is_ocean);
    return 0;
}
