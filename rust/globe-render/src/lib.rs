#![allow(clippy::missing_safety_doc, clippy::too_many_arguments)]

use std::f32::consts::PI as PI_F32;
use std::f64::consts::PI;
use std::slice;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{PoisonError, RwLock};
use std::thread;

const MAX_LEVELS: i32 = 16;
const GRADE_STEPS: usize = 4096;
const BLOOM_RADIUS: usize = 4;
const POLE_TEXELS: f32 = 3.0;
const DISTANCE_CAP: f32 = 255.0;
const HALO_STEPS: usize = 2048;
const HALO_RANGE: f32 = 0.5;
const BRIGHT_SCALE: f32 = 64.0;
const SHADOW_TEXELS: f32 = 0.9;
const WRAP_BIAS_TEXELS: f32 = 4096.0;
const ROW_CHUNK: usize = 8;
const BLUR_WEIGHTS: [f32; BLOOM_RADIUS + 1] = [0.2041, 0.1801, 0.1238, 0.0663, 0.0276];

#[repr(C)]
pub struct GlobeParams {
    light: [f32; 3],
    key_color: [f32; 3],
    rim_color: [f32; 3],
    sky_ambient: [f32; 3],
    ground_ambient: [f32; 3],
    atmosphere_lit: [f32; 3],
    atmosphere_dark: [f32; 3],
    emissive_color: [f32; 3],
    cloud_color: [f32; 3],
    warm_color: [f32; 3],
    warm_amount: f32,
    bump: f32,
    pitch_degrees: f32,
    shift: f32,
    cloud_shift: f32,
    exposure: f32,
    bloom_threshold: f32,
    bloom_strength: f32,
    grain_amount: f32,
    halo_extent: f32,
    grain_seed: u32,
}

#[repr(C)]
pub struct BakeParams {
    ocean_deep: [f32; 3],
    ocean_shelf: [f32; 3],
    land_low: [f32; 3],
    land_high: [f32; 3],
    lights_gain: f32,
    seed: u32,
}

struct Binding {
    color_address: usize,
    surface_address: usize,
    texel_count: usize,
    width: i32,
    height: i32,
    levels: i32,
    color_poles: [u32; 2],
    surface_poles: [u32; 2],
}

struct Tables {
    grade: [[f32; GRADE_STEPS + 1]; 3],
    halo: [f32; HALO_STEPS + 1],
}

static BINDING: RwLock<Option<Binding>> = RwLock::new(None);
static TABLES: RwLock<Tables> = RwLock::new(Tables {
    grade: [[0.0; GRADE_STEPS + 1]; 3],
    halo: [0.0; HALO_STEPS + 1],
});

#[derive(Clone, Copy)]
struct RowsMut<T> {
    base: *mut T,
    stride: usize,
    width: usize,
}

unsafe impl<T: Send> Send for RowsMut<T> {}
unsafe impl<T: Send> Sync for RowsMut<T> {}

impl<T> RowsMut<T> {
    fn new(base: *mut T, stride: usize, width: usize) -> Self {
        Self {
            base,
            stride,
            width,
        }
    }

    unsafe fn row<'a>(self, index: usize) -> &'a mut [T] {
        unsafe { slice::from_raw_parts_mut(self.base.add(index * self.stride), self.width) }
    }
}

fn parallel_rows<State>(
    rows: usize,
    make_state: impl Fn() -> State + Sync,
    work: impl Fn(&mut State, usize) + Sync,
) {
    let workers = thread::available_parallelism()
        .map_or(1, |count| count.get())
        .min(rows.div_ceil(ROW_CHUNK));
    if workers <= 1 {
        let mut state = make_state();
        (0..rows).for_each(|row| work(&mut state, row));
        return;
    }
    let next_row = AtomicUsize::new(0);
    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| {
                let mut state = make_state();
                loop {
                    let start = next_row.fetch_add(ROW_CHUNK, Ordering::Relaxed);
                    if start >= rows {
                        break;
                    }
                    for row in start..(start + ROW_CHUNK).min(rows) {
                        work(&mut state, row);
                    }
                }
            });
        }
    });
}

fn for_each_row(rows: usize, work: impl Fn(usize) + Sync) {
    parallel_rows(rows, || (), |_, row| work(row));
}

#[inline(always)]
fn clampf(value: f32, low: f32, high: f32) -> f32 {
    if value < low {
        low
    } else if value > high {
        high
    } else {
        value
    }
}

#[inline(always)]
fn smoothstepf(edge0: f32, edge1: f32, value: f32) -> f32 {
    let t = clampf((value - edge0) / (edge1 - edge0), 0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

#[inline(always)]
fn mixf(first: f32, second: f32, amount: f32) -> f32 {
    first + (second - first) * amount
}

#[inline(always)]
fn blend(first: u32, second: u32, weight: u32) -> u32 {
    let inverse = 256u32.wrapping_sub(weight);
    let red_blue = ((first & 0x00FF00FF)
        .wrapping_mul(inverse)
        .wrapping_add((second & 0x00FF00FF).wrapping_mul(weight))
        >> 8)
        & 0x00FF00FF;
    let alpha_green = ((first >> 8) & 0x00FF00FF)
        .wrapping_mul(inverse)
        .wrapping_add(((second >> 8) & 0x00FF00FF).wrapping_mul(weight))
        & 0xFF00FF00;
    red_blue | alpha_green
}

#[inline(always)]
fn channel(pixel: u32, shift: u32) -> u32 {
    (pixel >> shift) & 0xFF
}

#[inline(always)]
fn pack(alpha: u32, red: u32, green: u32, blue: u32) -> u32 {
    (alpha << 24) | (red << 16) | (green << 8) | blue
}

#[inline(always)]
fn to_byte(value: f32) -> u32 {
    clampf(value * 255.0 + 0.5, 0.0, 255.0) as u32
}

fn mip_levels(mut width: i32, mut height: i32) -> i32 {
    let mut levels = 1;
    while width > 1 && height > 1 && levels < MAX_LEVELS {
        width >>= 1;
        height >>= 1;
        levels += 1;
    }
    levels
}

fn chain_texels(width: i32, height: i32) -> usize {
    (0..mip_levels(width, height))
        .map(|level| (width >> level) as usize * (height >> level) as usize)
        .sum()
}

#[unsafe(no_mangle)]
pub extern "C" fn globe_mip_levels(width: i32, height: i32) -> i32 {
    mip_levels(width, height)
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn globe_build_mips(chain: *mut u32, width: i32, height: i32) {
    if chain.is_null() || width <= 0 || height <= 0 {
        return;
    }
    let chain = unsafe { slice::from_raw_parts_mut(chain, chain_texels(width, height)) };
    let mut source_offset = 0;
    for level in 1..mip_levels(width, height) {
        let source_width = (width >> (level - 1)) as usize;
        let source_height = (height >> (level - 1)) as usize;
        let target_width = (width >> level) as usize;
        let target_height = (height >> level) as usize;
        let (head, tail) = chain.split_at_mut(source_offset + source_width * source_height);
        let source = &head[source_offset..];
        let target = RowsMut::new(tail.as_mut_ptr(), target_width, target_width);
        for_each_row(target_height, |row| {
            let output = unsafe { target.row(row) };
            let upper = &source[2 * row * source_width..][..source_width];
            let lower = &source[(2 * row + 1) * source_width..][..source_width];
            for (column, texel) in output.iter_mut().enumerate() {
                let corners = [
                    upper[2 * column],
                    upper[2 * column + 1],
                    lower[2 * column],
                    lower[2 * column + 1],
                ];
                *texel = (0..4).fold(0, |result, index| {
                    let shift = index * 8;
                    let sum: u32 = corners.iter().map(|&pixel| channel(pixel, shift)).sum();
                    result | (((sum + 2) >> 2) << shift)
                });
            }
        });
        source_offset += source_width * source_height;
    }
}

fn row_average(row: &[u32]) -> u32 {
    let mut sums = [0u64; 4];
    for &pixel in row {
        for (index, sum) in sums.iter_mut().enumerate() {
            *sum += u64::from(channel(pixel, index as u32 * 8));
        }
    }
    sums.iter().enumerate().fold(0, |result, (index, &sum)| {
        result | (((sum / row.len() as u64) as u32) << (index * 8))
    })
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn globe_bind(
    color: *const u32,
    surface: *const u32,
    width: i32,
    height: i32,
) {
    let mut binding = BINDING.write().unwrap_or_else(PoisonError::into_inner);
    if color.is_null()
        || surface.is_null()
        || width <= 0
        || height <= 0
        || !(width as u32).is_power_of_two()
    {
        *binding = None;
        return;
    }
    let texel_count = chain_texels(width, height);
    let color_texels = unsafe { slice::from_raw_parts(color, texel_count) };
    let surface_texels = unsafe { slice::from_raw_parts(surface, texel_count) };
    let row_width = width as usize;
    let last_row = (height as usize - 1) * row_width;
    *binding = Some(Binding {
        color_address: color as usize,
        surface_address: surface as usize,
        texel_count,
        width,
        height,
        levels: mip_levels(width, height),
        color_poles: [
            row_average(&color_texels[..row_width]),
            row_average(&color_texels[last_row..last_row + row_width]),
        ],
        surface_poles: [
            row_average(&surface_texels[..row_width]),
            row_average(&surface_texels[last_row..last_row + row_width]),
        ],
    });
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn globe_grade(gamma: *const f32, lift: *const f32) {
    if gamma.is_null() || lift.is_null() {
        return;
    }
    let gamma = unsafe { slice::from_raw_parts(gamma, 3) };
    let lift = unsafe { slice::from_raw_parts(lift, 3) };
    let mut tables = TABLES.write().unwrap_or_else(PoisonError::into_inner);
    for (step, density) in tables.halo.iter_mut().enumerate() {
        let outside = step as f32 * HALO_RANGE / HALO_STEPS as f32;
        *density = (0.85 * (-outside / 0.016).exp() + 0.2 * (-outside / 0.075).exp()).min(1.0);
    }
    for (component, table) in tables.grade.iter_mut().enumerate() {
        for (step, graded) in table.iter_mut().enumerate() {
            let mut value = (step as f32 / GRADE_STEPS as f32).powf(gamma[component]);
            value += lift[component] * (1.0 - value);
            let encoded = if value <= 0.0031308 {
                value * 12.92
            } else {
                1.055 * value.powf(1.0 / 2.4) - 0.055
            };
            *graded = clampf(encoded, 0.0, 1.0) * 255.0;
        }
    }
}

fn project(
    mut sx: f64,
    mut sy: f64,
    cos_pitch: f64,
    sin_pitch: f64,
    texture_width: f64,
    texture_height: f64,
) -> (f64, f64) {
    let distance_squared = sx * sx + sy * sy;
    let sz = if distance_squared < 1.0 {
        (1.0 - distance_squared).sqrt()
    } else {
        0.0
    };
    if distance_squared > 1.0 {
        let length = distance_squared.sqrt();
        sx /= length;
        sy /= length;
    }
    let world_y = (sy * cos_pitch + sz * sin_pitch).clamp(-1.0, 1.0);
    let world_z = -sy * sin_pitch + sz * cos_pitch;
    (
        (sx.atan2(world_z) / (2.0 * PI) + 0.5) * texture_width,
        (0.5 - world_y.asin() / PI) * texture_height,
    )
}

fn wrapped_difference(first: f64, second: f64, texture_width: f64) -> f64 {
    let difference = first - second;
    if difference > texture_width / 2.0 {
        difference - texture_width
    } else if difference < -texture_width / 2.0 {
        difference + texture_width
    } else {
        difference
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn globe_prepare(
    size: i32,
    radius: f32,
    pitch_degrees: f64,
    texture_width: i32,
    texture_height: i32,
    u: *mut f32,
    v: *mut f32,
    lod: *mut f32,
) {
    if size <= 0 || radius <= 0.0 || u.is_null() || v.is_null() || lod.is_null() {
        return;
    }
    let size = size as usize;
    let u_rows = RowsMut::new(u, size, size);
    let v_rows = RowsMut::new(v, size, size);
    let lod_rows = RowsMut::new(lod, size, size);
    let pitch = pitch_degrees * PI / 180.0;
    let (sin_pitch, cos_pitch) = pitch.sin_cos();
    let center = size as f64 / 2.0;
    let radius = f64::from(radius);
    let step = 1.0 / radius;
    let reach = (1.0 + 2.0 * step) * (1.0 + 2.0 * step);
    let texture_width = f64::from(texture_width);
    let texture_height = f64::from(texture_height);
    for_each_row(size, |row| {
        let (u_row, v_row, lod_row) =
            unsafe { (u_rows.row(row), v_rows.row(row), lod_rows.row(row)) };
        let sy = (center - (row as f64 + 0.5)) / radius;
        for column in 0..size {
            let sx = ((column as f64 + 0.5) - center) / radius;
            if sx * sx + sy * sy > reach {
                u_row[column] = 0.0;
                v_row[column] = 0.0;
                lod_row[column] = 0.0;
                continue;
            }
            let project_at =
                |x, y| project(x, y, cos_pitch, sin_pitch, texture_width, texture_height);
            let (pixel_u, pixel_v) = project_at(sx, sy);
            let (right_u, right_v) = project_at(sx + step, sy);
            let (down_u, down_v) = project_at(sx, sy - step);
            let horizontal_u = wrapped_difference(right_u, pixel_u, texture_width);
            let horizontal_v = right_v - pixel_v;
            let vertical_u = wrapped_difference(down_u, pixel_u, texture_width);
            let vertical_v = down_v - pixel_v;
            let footprint = (horizontal_u * horizontal_u + horizontal_v * horizontal_v)
                .max(vertical_u * vertical_u + vertical_v * vertical_v);
            let level = if footprint > 1.0 {
                0.5 * footprint.log2() - 0.25
            } else {
                0.0
            };
            u_row[column] = pixel_u as f32;
            v_row[column] = pixel_v as f32;
            lod_row[column] = level.max(0.0) as f32;
        }
    });
}

struct Taps {
    indices: [usize; 4],
    weight_x: u32,
    weight_y: u32,
}

struct Frame<'a> {
    color_source: &'a [u32],
    surface_source: &'a [u32],
    tables: &'a Tables,
    color_poles: [u32; 2],
    surface_poles: [u32; 2],
    cos_pitch: f32,
    sin_pitch: f32,
    light: [f32; 3],
    half: [f32; 3],
    rim: [f32; 3],
    planar_x: f32,
    planar_y: f32,
    planar_length: f32,
    backlight: f32,
    key: [f32; 3],
    warm: [f32; 3],
    rim_color: [f32; 3],
    sky_ambient: [f32; 3],
    ground_ambient: [f32; 3],
    atmosphere_lit: [f32; 3],
    atmosphere_dark: [f32; 3],
    emissive_color: [f32; 3],
    cloud_color: [f32; 3],
    warm_amount: f32,
    bump: f32,
    exposure: f32,
    shift: f32,
    cloud_shift: f32,
    bloom_threshold: f32,
    grain_amount: f32,
    grain_seed: u32,
    center: f32,
    radius: f32,
    inverse_radius: f32,
    aberration: f32,
    shadow_shift_x: f32,
    shadow_shift_y: f32,
    texture_height: f32,
    base_width: i32,
    base_height: i32,
    last_level: i32,
    quarter: usize,
}

struct Row<'a> {
    u: &'a [f32],
    v: &'a [f32],
    lod: &'a [f32],
    glow: &'a [f32],
    sy: f32,
    index: u32,
    line: &'a mut [u32],
    bright: &'a mut [u32],
}

impl Frame<'_> {
    #[inline(always)]
    fn level_taps(&self, level: i32, u: f32, v: f32) -> Taps {
        let width = self.base_width >> level;
        let height = self.base_height >> level;
        let texels = i64::from(self.base_width) * i64::from(self.base_height);
        let offset = (4 * (texels - (texels >> (2 * level))) / 3) as i32;
        let scale = f32::from_bits(((127 - level) as u32) << 23);
        let fu = u * scale - 0.5;
        let fv = clampf(v * scale - 0.5, 0.0, (height - 1) as f32);
        let ix = ((fu + WRAP_BIAS_TEXELS) * 256.0) as i32;
        let iy = (fv * 256.0) as i32;
        let x0 = (ix >> 8) & (width - 1);
        let x1 = (x0 + 1) & (width - 1);
        let y0 = iy >> 8;
        let y1 = if y0 + 1 < height { y0 + 1 } else { height - 1 };
        let top = offset + y0 * width;
        let bottom = offset + y1 * width;
        Taps {
            indices: [
                (top + x0) as usize,
                (top + x1) as usize,
                (bottom + x0) as usize,
                (bottom + x1) as usize,
            ],
            weight_x: (ix & 0xFF) as u32,
            weight_y: (iy & 0xFF) as u32,
        }
    }

    #[inline(always)]
    fn halo_density(&self, outside: f32) -> f32 {
        self.tables.halo
            [(clampf(outside, 0.0, HALO_RANGE) * (HALO_STEPS as f32 / HALO_RANGE)) as usize]
    }

    #[inline(always)]
    fn graded(&self, component: usize, value: f32) -> f32 {
        self.tables.grade[component][(value * GRADE_STEPS as f32) as usize]
    }

    #[inline(always)]
    fn bloom_at(&self, row: &Row, column: usize) -> [f32; 3] {
        let bloom_x = (column as f32 + 0.5) * 0.25 - 0.5;
        let left = bloom_x.floor() as i32;
        let weight_x = bloom_x - left as f32;
        let right = if left + 1 < self.quarter as i32 {
            (left + 1) as usize
        } else {
            self.quarter - 1
        };
        let left = left.max(0) as usize;
        std::array::from_fn(|component| {
            mixf(
                row.glow[left * 3 + component],
                row.glow[right * 3 + component],
                weight_x,
            )
        })
    }

    #[inline(always)]
    fn shade_halo(&self, sx: f32, sy: f32, distance: f32, glow: &[f32; 3]) -> ([f32; 3], f32) {
        let outside = distance - 1.0;
        let mut lit = clampf(
            ((sx * self.planar_x + sy * self.planar_y) / distance) * self.planar_length * 0.8
                + 0.42
                + 0.6 * self.backlight,
            0.0,
            1.0,
        );
        lit = lit * lit * (3.0 - 2.0 * lit);
        let strength = 0.35 + 0.65 * lit;
        let densities = [
            self.halo_density(outside - self.aberration) * strength,
            self.halo_density(outside) * strength,
            self.halo_density(outside + self.aberration) * strength,
        ];
        let alpha = densities[0].max(densities[1].max(densities[2]));
        let mut brightest = 0.0f32;
        let halo = std::array::from_fn(|component| {
            let tint = mixf(
                self.atmosphere_dark[component],
                self.atmosphere_lit[component],
                lit,
            ) * (0.5 + 1.3 * lit);
            let value = tint * densities[component] + glow[component];
            brightest = brightest.max(value);
            value
        });
        (halo, clampf(alpha.max(brightest * 0.5), 0.0, 1.0))
    }

    #[inline(always)]
    fn sample(&self, texels: &[u32], taps: &Taps) -> u32 {
        let [top_left, top_right, bottom_left, bottom_right] = taps.indices;
        blend(
            blend(texels[top_left], texels[top_right], taps.weight_x),
            blend(texels[bottom_left], texels[bottom_right], taps.weight_x),
            taps.weight_y,
        )
    }

    #[inline(always)]
    fn shade_planet(
        &self,
        row: &Row,
        column: usize,
        sx: f32,
        sy: f32,
        distance_squared: f32,
        distance: f32,
        coverage: f32,
        glow: &[f32; 3],
    ) -> ([f32; 3], [f32; 3]) {
        let sz = (1.0 - distance_squared.min(1.0)).sqrt();
        let limb = if distance > 1.0 { 1.0 / distance } else { 1.0 };
        let normal_x = sx * limb;
        let normal_y = sy * limb;

        let pixel_u = row.u[column] + self.shift;
        let pixel_v = row.v[column];
        let pixel_lod = row.lod[column];
        let level = (pixel_lod as i32).clamp(0, self.last_level);
        let next_level = (level + 1).min(self.last_level);
        let mip_weight = (clampf(pixel_lod - level as f32, 0.0, 1.0) * 256.0) as u32;
        let taps = self.level_taps(level, pixel_u, pixel_v);
        let mut color = self.sample(self.color_source, &taps);
        let mut surface = self.sample(self.surface_source, &taps);
        let taps = self.level_taps(next_level, pixel_u, pixel_v);
        color = blend(color, self.sample(self.color_source, &taps), mip_weight);
        surface = blend(surface, self.sample(self.surface_source, &taps), mip_weight);
        let pole_distance = pixel_v.min(self.texture_height - pixel_v);
        let pole_weight = (clampf(1.0 - pole_distance / POLE_TEXELS, 0.0, 1.0) * 256.0) as u32;
        let pole = usize::from(pixel_v >= self.texture_height * 0.5);
        color = blend(color, self.color_poles[pole], pole_weight);
        surface = blend(surface, self.surface_poles[pole], pole_weight);
        let cloud_level = ((pixel_lod + 1.5) as i32).clamp(0, self.last_level);
        let taps = self.level_taps(cloud_level, row.u[column] + self.cloud_shift, pixel_v);
        let [
            cloud_top_left,
            cloud_top_right,
            cloud_bottom_left,
            cloud_bottom_right,
        ] = taps
            .indices
            .map(|index| channel(self.surface_source[index], 24) as f32 * (1.0 / 255.0));
        let cloud_x = taps.weight_x as f32 * (1.0 / 256.0);
        let cloud_y = taps.weight_y as f32 * (1.0 / 256.0);
        let cloud = mixf(
            mixf(cloud_top_left, cloud_top_right, cloud_x),
            mixf(cloud_bottom_left, cloud_bottom_right, cloud_x),
            cloud_y,
        );
        let shadow_x = clampf(cloud_x - self.shadow_shift_x, 0.0, 1.0);
        let shadow_y = clampf(cloud_y + self.shadow_shift_y, 0.0, 1.0);
        let cloud_shadow = mixf(
            mixf(cloud_top_left, cloud_top_right, shadow_x),
            mixf(cloud_bottom_left, cloud_bottom_right, shadow_x),
            shadow_y,
        );

        let (cos_pitch, sin_pitch) = (self.cos_pitch, self.sin_pitch);
        let world_y = normal_y * cos_pitch + sz * sin_pitch;
        let world_z = -normal_y * sin_pitch + sz * cos_pitch;
        let latitude_cos = (normal_x * normal_x + world_z * world_z).sqrt();
        let inverse_cos = 1.0 / latitude_cos.max(1e-4);
        let east_x = world_z * inverse_cos;
        let east_world_z = -normal_x * inverse_cos;
        let east_y = -east_world_z * sin_pitch;
        let east_z = east_world_z * cos_pitch;
        let north_x = -world_y * normal_x * inverse_cos;
        let north_world_z = -world_y * world_z * inverse_cos;
        let north_y = latitude_cos * cos_pitch - north_world_z * sin_pitch;
        let north_z = latitude_cos * sin_pitch + north_world_z * cos_pitch;
        let slope_east = (channel(surface, 16) as f32 - 128.0) * self.bump;
        let slope_north = (channel(surface, 8) as f32 - 128.0) * self.bump;
        let inverse_length =
            1.0 / (1.0 + slope_east * slope_east + slope_north * slope_north).sqrt();
        let bumped = [
            (normal_x - slope_east * east_x - slope_north * north_x) * inverse_length,
            (normal_y - slope_east * east_y - slope_north * north_y) * inverse_length,
            (sz - slope_east * east_z - slope_north * north_z) * inverse_length,
        ];
        let dot = |vector: &[f32; 3], other: &[f32; 3]| {
            vector[0] * other[0] + vector[1] * other[1] + vector[2] * other[2]
        };

        let geometric = dot(&[normal_x, normal_y, sz], &self.light);
        let facing = dot(&bumped, &self.light);
        let diffuse =
            clampf((facing + 0.3) * (1.0 / 1.3), 0.0, 1.0) * smoothstepf(-0.3, 0.15, geometric);
        let daylight = smoothstepf(-0.12, 0.32, geometric);
        let band_distance = (geometric - 0.03) * (1.0 / 0.24);
        let band = self.warm_amount * clampf(1.0 - band_distance * band_distance, 0.0, 1.0);
        let rim = clampf(dot(&bumped, &self.rim), 0.0, 1.0);
        let sky = bumped[1] * 0.5 + 0.5;
        let mut half_facing = clampf(dot(&bumped, &self.half), 0.0, 1.0);
        if half_facing <= 0.3 {
            half_facing = 0.0;
        }
        let mut broad = half_facing * half_facing;
        broad *= broad;
        broad *= broad;
        let mut glossy = broad * broad;
        glossy *= glossy;
        glossy *= glossy;
        let grazing = 1.0 - sz;
        let grazing_squared = grazing * grazing;
        let fresnel = 0.04 + 0.96 * grazing_squared * grazing_squared * grazing;
        let specular = channel(surface, 0) as f32
            * (1.0 / 255.0)
            * (1.0 - cloud)
            * (glossy + broad * 0.03)
            * (1.0 + 4.0 * fresnel)
            * daylight;
        let shadow = 1.0 - 0.45 * cloud_shadow * daylight;
        let night = 1.0 - daylight;
        let mut emissive = channel(color, 24) as f32 * (1.0 / 255.0);
        emissive *= emissive * night * night * (1.0 - 0.6 * cloud);
        let haze = grazing_squared * (0.35 + 0.25 * grazing);
        let haze_light = 0.25 + 1.1 * clampf(geometric + 0.25, 0.0, 1.0);
        let haze_mix = smoothstepf(-0.35, 0.5, geometric);
        let mut planet = [0.0; 3];
        let mut bright_light = [0.0; 3];
        for component in 0..3 {
            let encoded = channel(color, 16 - 8 * component as u32) as f32 * (1.0 / 255.0);
            let albedo = encoded * (encoded * (encoded * 0.305_306 + 0.682_171_1) + 0.012522878);
            let light = mixf(self.key[component], self.warm[component], band);
            let ambient = mixf(
                self.ground_ambient[component],
                self.sky_ambient[component],
                sky,
            );
            let mut lit =
                albedo * (light * diffuse * shadow + ambient) + self.rim_color[component] * rim;
            lit = mixf(
                lit,
                self.cloud_color[component] * (light * diffuse + ambient * 1.6),
                cloud * 0.8,
            );
            let specular_light = specular * light;
            let emission = emissive * self.emissive_color[component];
            lit += specular_light + emission;
            let atmosphere = mixf(
                self.atmosphere_dark[component],
                self.atmosphere_lit[component],
                haze_mix,
            ) * haze_light;
            planet[component] =
                (lit * (1.0 - haze * 0.6) + atmosphere * haze + glow[component]) * self.exposure;
            bright_light[component] = (specular_light + emission - self.bloom_threshold) * coverage;
        }
        (planet, bright_light)
    }

    #[inline(always)]
    fn render_span<const WITH_PLANET: bool, const WITH_HALO: bool>(
        &self,
        row: &mut Row,
        start: usize,
        end: usize,
    ) {
        for column in start..end {
            let sx = ((column as f32 + 0.5) - self.center) * self.inverse_radius;
            let sy = row.sy;
            let distance_squared = sx * sx + sy * sy;
            let distance = distance_squared.sqrt() + 1e-6;
            let coverage = match (WITH_PLANET, WITH_HALO) {
                (true, true) => clampf((1.0 - distance) * self.radius + 0.5, 0.0, 1.0),
                (true, false) => 1.0,
                _ => 0.0,
            };
            let glow = self.bloom_at(row, column);
            let (planet, bright_light) = if WITH_PLANET {
                self.shade_planet(
                    row,
                    column,
                    sx,
                    sy,
                    distance_squared,
                    distance,
                    coverage,
                    &glow,
                )
            } else {
                ([0.0; 3], [0.0; 3])
            };
            let (halo, halo_alpha) = if WITH_HALO {
                self.shade_halo(sx, sy, distance, &glow)
            } else {
                ([0.0; 3], 0.0)
            };
            let halo_weight = halo_alpha * (1.0 - coverage);
            let inverse_halo = if halo_alpha > 0.0 {
                self.exposure / halo_alpha.max(1e-6)
            } else {
                0.0
            };
            let alpha = coverage + halo_weight;
            let dither =
                self.grain_amount * grain(column as u32, row.index, self.grain_seed) * alpha;
            let limit = alpha * 255.0;
            let mut components = [0u32; 3];
            let mut bright_components = [0u32; 3];
            for component in 0..3 {
                let mut value = dither;
                if WITH_PLANET {
                    value += self.graded(component, tone_map(planet[component])) * coverage;
                }
                if WITH_HALO {
                    value += self.graded(component, tone_map(halo[component] * inverse_halo))
                        * halo_weight;
                }
                components[component] = clampf(value + 0.5, 0.0, limit) as u32;
                bright_components[component] =
                    clampf(bright_light[component] * BRIGHT_SCALE, 0.0, 255.0) as u32;
            }
            let pixel = pack(
                (alpha * 255.0 + 0.5) as u32,
                components[0],
                components[1],
                components[2],
            );
            row.line[column] = if alpha > 0.002 { pixel } else { 0 };
            row.bright[column] = pack(
                0,
                bright_components[0],
                bright_components[1],
                bright_components[2],
            );
        }
    }
}

#[inline(always)]
fn tone_map(value: f32) -> f32 {
    let value = value.max(0.0);
    ((value * (2.51 * value + 0.03)) / (value * (2.43 * value + 0.59) + 0.14)).min(1.0)
}

#[inline(always)]
fn grain(column: u32, row: u32, seed: u32) -> f32 {
    let mut hash = column.wrapping_mul(0x8da6b343) ^ row.wrapping_mul(0xd8163841) ^ seed;
    hash ^= hash >> 15;
    hash = hash.wrapping_mul(0x2c1b3c6d);
    hash ^= hash >> 12;
    (hash & 0xFFFF) as f32 / 32767.5 - 1.0
}

fn blur_horizontal(source: &[f32], target: &mut [f32], size: usize) {
    let span = size * 3;
    for (line, output) in source.chunks_exact(span).zip(target.chunks_exact_mut(span)) {
        for (out, &value) in output.iter_mut().zip(line) {
            *out = value * BLUR_WEIGHTS[0];
        }
        for (offset, &weight) in BLUR_WEIGHTS.iter().enumerate().skip(1) {
            let shift = offset * 3;
            if shift >= span {
                break;
            }
            for index in shift..span {
                output[index] += line[index - shift] * weight;
            }
            for index in 0..span - shift {
                output[index] += line[index + shift] * weight;
            }
        }
    }
}

fn blur_vertical(source: &[f32], target: &mut [f32], size: usize) {
    let span = size * 3;
    for (row, output) in target.chunks_exact_mut(span).enumerate() {
        for (out, &value) in output.iter_mut().zip(&source[row * span..][..span]) {
            *out = value * BLUR_WEIGHTS[0];
        }
        for (offset, &weight) in BLUR_WEIGHTS.iter().enumerate().skip(1) {
            let neighbours = [
                row.checked_sub(offset),
                Some(row + offset).filter(|&below| below < size),
            ];
            for neighbour in neighbours.into_iter().flatten() {
                for (out, &value) in output.iter_mut().zip(&source[neighbour * span..][..span]) {
                    *out += value * weight;
                }
            }
        }
    }
}

fn downsample_bright(bright: &[u32], size: usize, accumulator: &mut [f32], quarter: usize) {
    let normalize = 1.0 / (16.0 * BRIGHT_SCALE);
    for row in 0..quarter {
        for column in 0..quarter {
            let mut sums = [0u32; 3];
            for y in row * 4..(row * 4 + 4).min(size) {
                for x in column * 4..(column * 4 + 4).min(size) {
                    let pixel = bright[y * size + x];
                    sums[0] += channel(pixel, 16);
                    sums[1] += channel(pixel, 8);
                    sums[2] += channel(pixel, 0);
                }
            }
            let out = &mut accumulator[(row * quarter + column) * 3..][..3];
            for (value, sum) in out.iter_mut().zip(sums) {
                *value = sum as f32 * normalize;
            }
        }
    }
}

fn clamp_column(column: i32, low: i32, high: i32) -> i32 {
    if column < low {
        low
    } else if column > high {
        high
    } else {
        column
    }
}

fn half_chord(extent: f32, sy: f32, radius: f32) -> f32 {
    let squared = extent * extent - sy * sy;
    if squared > 0.0 {
        squared.sqrt() * radius
    } else {
        -1.0
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn globe_render(
    params: *const GlobeParams,
    u: *const f32,
    v: *const f32,
    lod: *const f32,
    size: i32,
    radius: f32,
    output: *mut u32,
    output_stride: i32,
    bright: *mut u32,
    bloom_accumulator: *mut f32,
    bloom_scratch: *mut f32,
    bloom: *mut f32,
) {
    if params.is_null()
        || u.is_null()
        || v.is_null()
        || lod.is_null()
        || output.is_null()
        || bright.is_null()
        || bloom_accumulator.is_null()
        || bloom_scratch.is_null()
        || bloom.is_null()
        || size <= 0
        || radius <= 0.0
        || output_stride < size * 4
    {
        return;
    }
    let binding_guard = BINDING.read().unwrap_or_else(PoisonError::into_inner);
    let Some(binding) = binding_guard.as_ref() else {
        return;
    };
    let tables_guard = TABLES.read().unwrap_or_else(PoisonError::into_inner);
    let params = unsafe { &*params };
    let pixel_size = size as usize;
    let pixels = pixel_size * pixel_size;
    let quarter = pixel_size.div_ceil(4);
    let bloom_length = quarter * quarter * 3;
    let (u, v, lod) = unsafe {
        (
            slice::from_raw_parts(u, pixels),
            slice::from_raw_parts(v, pixels),
            slice::from_raw_parts(lod, pixels),
        )
    };
    let bloom = unsafe { slice::from_raw_parts_mut(bloom, bloom_length) };
    let output_rows = RowsMut::new(output, output_stride as usize / 4, pixel_size);
    let bright_rows = RowsMut::new(bright, pixel_size, pixel_size);

    let light = params.light;
    let half_vector = [light[0], light[1], light[2] + 1.0];
    let half_length = (half_vector[0] * half_vector[0]
        + half_vector[1] * half_vector[1]
        + half_vector[2] * half_vector[2])
        .sqrt();
    let half_length = if half_length > 1e-6 { half_length } else { 1.0 };
    let planar_length = (light[0] * light[0] + light[1] * light[1]).sqrt();
    let planar_direction = |axis: f32| {
        if planar_length > 1e-4 {
            axis / planar_length
        } else {
            0.0
        }
    };
    let (sin_pitch, cos_pitch) = (params.pitch_degrees * PI_F32 / 180.0).sin_cos();
    let inverse_radius = 1.0 / radius;
    let frame = Frame {
        color_source: unsafe {
            slice::from_raw_parts(binding.color_address as *const u32, binding.texel_count)
        },
        surface_source: unsafe {
            slice::from_raw_parts(binding.surface_address as *const u32, binding.texel_count)
        },
        tables: &tables_guard,
        color_poles: binding.color_poles,
        surface_poles: binding.surface_poles,
        cos_pitch,
        sin_pitch,
        light,
        half: half_vector.map(|axis| axis / half_length),
        rim: [-0.3 * light[0], 0.35, -0.88],
        planar_x: planar_direction(light[0]),
        planar_y: planar_direction(light[1]),
        planar_length,
        backlight: if light[2] < 0.0 { -light[2] } else { 0.0 },
        key: params.key_color,
        warm: params.warm_color.map(|value| value * 1.4),
        rim_color: params.rim_color.map(|value| value * 0.35),
        sky_ambient: params.sky_ambient,
        ground_ambient: params.ground_ambient,
        atmosphere_lit: params.atmosphere_lit,
        atmosphere_dark: params.atmosphere_dark,
        emissive_color: params.emissive_color,
        cloud_color: params.cloud_color,
        warm_amount: params.warm_amount,
        bump: params.bump / 127.0,
        exposure: params.exposure,
        shift: params.shift,
        cloud_shift: params.cloud_shift,
        bloom_threshold: params.bloom_threshold,
        grain_amount: params.grain_amount,
        grain_seed: params.grain_seed,
        center: size as f32 / 2.0,
        radius,
        inverse_radius,
        aberration: 0.5 * inverse_radius,
        shadow_shift_x: light[0] * SHADOW_TEXELS,
        shadow_shift_y: light[1] * SHADOW_TEXELS,
        texture_height: binding.height as f32,
        base_width: binding.width,
        base_height: binding.height,
        last_level: binding.levels - 1,
        quarter,
    };
    let bloom_strength = params.bloom_strength;
    let halo_extent = params.halo_extent;
    let edge = 1.0 / radius;
    let bloom_source: &[f32] = bloom;
    let row_span = quarter * 3;

    parallel_rows(
        pixel_size,
        || vec![0.0f32; row_span],
        |glow, row_index| {
            let bloom_y = (row_index as f32 + 0.5) * 0.25 - 0.5;
            let upper = bloom_y.floor() as i32;
            let bloom_weight_y = bloom_y - upper as f32;
            let lower = if upper + 1 >= quarter as i32 {
                quarter - 1
            } else {
                (upper + 1) as usize
            };
            let upper = upper.max(0) as usize;
            let bloom_upper = &bloom_source[upper * row_span..][..row_span];
            let bloom_lower = &bloom_source[lower * row_span..][..row_span];
            for ((value, &top), &bottom) in glow.iter_mut().zip(bloom_upper).zip(bloom_lower) {
                *value = mixf(top, bottom, bloom_weight_y) * bloom_strength;
            }

            let mut row = Row {
                u: &u[row_index * pixel_size..][..pixel_size],
                v: &v[row_index * pixel_size..][..pixel_size],
                lod: &lod[row_index * pixel_size..][..pixel_size],
                glow,
                sy: (frame.center - (row_index as f32 + 0.5)) * inverse_radius,
                index: row_index as u32,
                line: unsafe { output_rows.row(row_index) },
                bright: unsafe { bright_rows.row(row_index) },
            };
            let center = frame.center - 0.5;
            let halo_half = half_chord(halo_extent, row.sy, radius);
            let outer_half = half_chord(1.0 + edge, row.sy, radius);
            let inner_half = half_chord(1.0 - edge, row.sy, radius);
            let start = if halo_half < 0.0 {
                size
            } else {
                clamp_column((center - halo_half).floor() as i32, 0, size)
            };
            let end = if halo_half < 0.0 {
                size
            } else {
                clamp_column((center + halo_half).ceil() as i32 + 1, start, size)
            };
            let outer_left = if outer_half < 0.0 {
                end
            } else {
                clamp_column((center - outer_half).floor() as i32, start, end)
            };
            let outer_right = if outer_half < 0.0 {
                end
            } else {
                clamp_column((center + outer_half).ceil() as i32 + 1, outer_left, end)
            };
            let inner_left = if inner_half < 0.0 {
                outer_left
            } else {
                clamp_column((center - inner_half).ceil() as i32, outer_left, outer_right)
            };
            let inner_right = if inner_half < 0.0 {
                outer_left
            } else {
                clamp_column(
                    (center + inner_half).floor() as i32 + 1,
                    inner_left,
                    outer_right,
                )
            };
            let [start, end, outer_left, outer_right, inner_left, inner_right] =
                [start, end, outer_left, outer_right, inner_left, inner_right]
                    .map(|column| column as usize);
            row.line[..start].fill(0);
            row.line[end..].fill(0);
            row.bright[..start].fill(0);
            row.bright[end..].fill(0);
            frame.render_span::<false, true>(&mut row, start, outer_left);
            frame.render_span::<true, true>(&mut row, outer_left, inner_left);
            render_interior(&frame, &mut row, inner_left, inner_right);
            frame.render_span::<true, true>(&mut row, inner_right, outer_right);
            frame.render_span::<false, true>(&mut row, outer_right, end);
        },
    );

    let (bright, accumulator, scratch) = unsafe {
        (
            slice::from_raw_parts(bright, pixels),
            slice::from_raw_parts_mut(bloom_accumulator, bloom_length),
            slice::from_raw_parts_mut(bloom_scratch, bloom_length),
        )
    };
    downsample_bright(bright, pixel_size, accumulator, quarter);
    blur_horizontal(accumulator, scratch, quarter);
    blur_vertical(scratch, bloom, quarter);
}

#[inline(always)]
fn lattice_value(x: i32, y: i32, z: i32, seed: u32) -> f32 {
    let mut hash = seed
        ^ (x as u32).wrapping_mul(0x8da6b343)
        ^ (y as u32).wrapping_mul(0xd8163841)
        ^ (z as u32).wrapping_mul(0xcb1ab31f);
    hash ^= hash >> 13;
    hash = hash.wrapping_mul(0x5bd1e995);
    hash ^= hash >> 15;
    (hash & 0xFFFFFF) as f32 / 16777215.0
}

#[inline(always)]
fn fade(t: f32) -> f32 {
    t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
}

fn value_noise(x: f32, y: f32, z: f32, seed: u32) -> f32 {
    let (fx, fy, fz) = (x.floor(), y.floor(), z.floor());
    let (ix, iy, iz) = (fx as i32, fy as i32, fz as i32);
    let (tx, ty, tz) = (fade(x - fx), fade(y - fy), fade(z - fz));
    let corner = |dx: i32, dy: i32, dz: i32| {
        lattice_value(
            ix.wrapping_add(dx),
            iy.wrapping_add(dy),
            iz.wrapping_add(dz),
            seed,
        )
    };
    mixf(
        mixf(
            mixf(corner(0, 0, 0), corner(1, 0, 0), tx),
            mixf(corner(0, 1, 0), corner(1, 1, 0), tx),
            ty,
        ),
        mixf(
            mixf(corner(0, 0, 1), corner(1, 0, 1), tx),
            mixf(corner(0, 1, 1), corner(1, 1, 1), tx),
            ty,
        ),
        tz,
    )
}

fn fbm(mut x: f32, mut y: f32, mut z: f32, octaves: u32, seed: u32) -> f32 {
    let (mut sum, mut amplitude, mut total) = (0.0, 0.5, 0.0);
    for octave in 0..octaves {
        sum += value_noise(x, y, z, seed.wrapping_add(octave.wrapping_mul(0x9e3779b9))) * amplitude;
        total += amplitude;
        amplitude *= 0.5;
        x = x * 2.03 + 17.1;
        y = y * 2.03 - 9.7;
        z = z * 2.03 + 4.3;
    }
    sum / total
}

fn distance_to_outside(
    inside: &[bool],
    width: usize,
    height: usize,
    padding: usize,
    distance: &mut [f32],
) {
    let padded = width + 2 * padding;
    let diagonal = std::f32::consts::SQRT_2;
    for row in 0..height {
        for column in 0..padded {
            let source = (column + width * padding - padding) % width;
            distance[row * padded + column] = if inside[row * width + source] {
                DISTANCE_CAP
            } else {
                0.0
            };
        }
    }
    for row in 0..height {
        for column in 0..padded {
            let index = row * padded + column;
            let mut best = distance[index];
            if column > 0 {
                best = best.min(distance[index - 1] + 1.0);
            }
            if row > 0 {
                let above = index - padded;
                best = best.min(distance[above] + 1.0);
                if column > 0 {
                    best = best.min(distance[above - 1] + diagonal);
                }
                if column + 1 < padded {
                    best = best.min(distance[above + 1] + diagonal);
                }
            }
            distance[index] = best;
        }
    }
    for row in (0..height).rev() {
        for column in (0..padded).rev() {
            let index = row * padded + column;
            let mut best = distance[index];
            if column + 1 < padded {
                best = best.min(distance[index + 1] + 1.0);
            }
            if row + 1 < height {
                let below = index + padded;
                best = best.min(distance[below] + 1.0);
                if column > 0 {
                    best = best.min(distance[below - 1] + diagonal);
                }
                if column + 1 < padded {
                    best = best.min(distance[below + 1] + diagonal);
                }
            }
            distance[index] = best;
        }
    }
}

fn try_filled<T: Clone>(count: usize, value: T) -> Option<Vec<T>> {
    let mut buffer = Vec::new();
    buffer.try_reserve_exact(count).ok()?;
    buffer.resize(count, value);
    Some(buffer)
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn globe_bake(
    land: *const u8,
    land_stride: i32,
    coast: *const u32,
    coast_stride: i32,
    lights: *const u8,
    lights_stride: i32,
    source_width: i32,
    source_height: i32,
    params: *const BakeParams,
    color_out: *mut u32,
    surface_out: *mut u32,
    width: i32,
    height: i32,
) -> i32 {
    if land.is_null()
        || coast.is_null()
        || lights.is_null()
        || params.is_null()
        || color_out.is_null()
        || surface_out.is_null()
        || width <= 0
        || height <= 0
        || source_width <= 0
        || source_height <= 0
        || land_stride < source_width
        || lights_stride < source_width
        || coast_stride < source_width * 4
    {
        return -1;
    }
    let factor = source_width / width;
    if factor < 1 || source_height / height != factor {
        return -1;
    }
    let params = unsafe { &*params };
    let source_rows = source_height as usize;
    let land_stride = land_stride as usize;
    let lights_stride = lights_stride as usize;
    let coast_stride = coast_stride as usize / 4;
    let (land, coast, lights) = unsafe {
        (
            slice::from_raw_parts(land, source_rows * land_stride),
            slice::from_raw_parts(coast, source_rows * coast_stride),
            slice::from_raw_parts(lights, source_rows * lights_stride),
        )
    };
    let factor = factor as usize;
    let width = width as usize;
    let height = height as usize;
    let count = width * height;
    let padding = DISTANCE_CAP as usize + 1;
    let padded = width + 2 * padding;
    let (
        Some(mut coverage),
        Some(mut heights),
        Some(mut land_distance),
        Some(mut ocean_distance),
        Some(mut is_land),
    ) = (
        try_filled(count, 0.0f32),
        try_filled(count, 0.0f32),
        try_filled(padded * height, 0.0f32),
        try_filled(padded * height, 0.0f32),
        try_filled(count, false),
    )
    else {
        return -2;
    };
    let block_area = (factor * factor) as f32;

    let coverage_rows = RowsMut::new(coverage.as_mut_ptr(), width, width);
    let land_rows = RowsMut::new(is_land.as_mut_ptr(), width, width);
    for_each_row(height, |row| {
        let (coverage_row, land_row) = unsafe { (coverage_rows.row(row), land_rows.row(row)) };
        for column in 0..width {
            let sum: u32 = (0..factor)
                .map(|y| {
                    land[(row * factor + y) * land_stride + column * factor..][..factor]
                        .iter()
                        .map(|&value| u32::from(value))
                        .sum::<u32>()
                })
                .sum();
            coverage_row[column] = sum as f32 / (255.0 * block_area);
            land_row[column] = coverage_row[column] >= 0.5;
        }
    });
    let is_ocean: Vec<bool> = is_land.iter().map(|&land_texel| !land_texel).collect();
    distance_to_outside(&is_land, width, height, padding, &mut land_distance);
    distance_to_outside(&is_ocean, width, height, padding, &mut ocean_distance);

    let seed = params.seed;
    let latitude_of = |row: usize| (0.5 - (row as f32 + 0.5) / height as f32) * PI_F32;
    let longitude_of = |column: usize| ((column as f32 + 0.5) / width as f32 - 0.5) * 2.0 * PI_F32;
    let height_rows = RowsMut::new(heights.as_mut_ptr(), width, width);
    for_each_row(height, |row| {
        let height_row = unsafe { height_rows.row(row) };
        let (sin_latitude, cos_latitude) = latitude_of(row).sin_cos();
        for (column, texel_height) in height_row.iter_mut().enumerate() {
            let (sin_longitude, cos_longitude) = longitude_of(column).sin_cos();
            let (px, py, pz) = (
                cos_latitude * cos_longitude,
                sin_latitude,
                cos_latitude * sin_longitude,
            );
            let padded_index = row * padded + column + padding;
            let inland = land_distance[padded_index];
            let offshore = ocean_distance[padded_index];
            let relief = fbm(px * 6.0, py * 6.0, pz * 6.0, 6, seed);
            let ridges = 1.0
                - (fbm(px * 11.0, py * 11.0, pz * 11.0, 5, seed.wrapping_add(101)) * 2.0 - 1.0)
                    .abs();
            let land_height = 0.12
                + 0.4 * smoothstepf(0.0, 36.0, inland) * (0.35 + 0.65 * ridges * relief * 1.4)
                + 0.1 * relief;
            let ocean_height = -0.05 * smoothstepf(0.0, 30.0, offshore) + 0.02 * relief;
            *texel_height = mixf(ocean_height, land_height, coverage[row * width + column]);
        }
    });

    let color_rows = RowsMut::new(color_out, width, width);
    let surface_rows = RowsMut::new(surface_out, width, width);
    let heights = &heights;
    let coverage = &coverage;
    for_each_row(height, |row| {
        let (color_row, surface_row) = unsafe { (color_rows.row(row), surface_rows.row(row)) };
        let (sin_latitude, latitude_cos) = latitude_of(row).sin_cos();
        let east_scale = 1.0 / latitude_cos.max(0.35);
        let row_above = row.saturating_sub(1);
        let row_below = (row + 1).min(height - 1);
        for column in 0..width {
            let index = row * width + column;
            let padded_index = row * padded + column + padding;
            let (sin_longitude, cos_longitude) = longitude_of(column).sin_cos();
            let (px, py, pz) = (
                latitude_cos * cos_longitude,
                sin_latitude,
                latitude_cos * sin_longitude,
            );
            let left = (column + width - 1) % width;
            let right = (column + 1) % width;
            let slope_east = (heights[row * width + right] - heights[row * width + left])
                * 0.5
                * east_scale
                * 22.0;
            let slope_north = (heights[row_above * width + column]
                - heights[row_below * width + column])
                * 0.5
                * 22.0;
            let land_amount = coverage[index];
            let inland = land_distance[padded_index];
            let offshore = ocean_distance[padded_index];
            let variation = fbm(px * 14.0, py * 14.0, pz * 14.0, 5, seed.wrapping_add(211));
            let tint = fbm(px * 3.0, py * 3.0, pz * 3.0, 3, seed.wrapping_add(307));
            let warp = fbm(px * 2.0, py * 2.0, pz * 2.0, 3, seed.wrapping_add(401)) * 1.6;
            let cloud_noise = fbm(
                px * 3.2 + warp,
                py * 5.5 - warp,
                pz * 3.2 + warp,
                6,
                seed.wrapping_add(503),
            );
            let cloud = smoothstepf(0.56, 0.8, cloud_noise)
                * (0.5 + 0.4 * smoothstepf(0.0, 0.35, py.abs()));
            let shelf = 1.0 - smoothstepf(0.0, 26.0, offshore);
            let elevation = smoothstepf(4.0, 60.0, inland) * (0.6 + 0.4 * variation);

            let mut coast_sum = [0.0f32; 4];
            let mut light_sum = 0u32;
            for y in 0..factor {
                let source_row = row * factor + y;
                let coast_row = &coast[source_row * coast_stride + column * factor..][..factor];
                let light_row = &lights[source_row * lights_stride + column * factor..][..factor];
                for (&coast_pixel, &light) in coast_row.iter().zip(light_row) {
                    for (component, sum) in coast_sum.iter_mut().enumerate() {
                        *sum += channel(coast_pixel, 24 - 8 * component as u32) as f32;
                    }
                    light_sum += u32::from(light);
                }
            }
            let coast_alpha = coast_sum[0] / (255.0 * block_area);
            let albedo: [f32; 3] = std::array::from_fn(|component| {
                let ocean = mixf(
                    params.ocean_deep[component],
                    params.ocean_shelf[component],
                    shelf,
                ) * (0.9 + 0.2 * tint);
                let ground = mixf(
                    params.land_low[component],
                    params.land_high[component],
                    elevation,
                ) * (0.82 + 0.36 * variation);
                let base = mixf(ocean, ground, land_amount);
                coast_sum[component + 1] / (255.0 * block_area) + base * (1.0 - coast_alpha)
            });
            let emission = clampf(
                light_sum as f32 / (255.0 * block_area) * params.lights_gain,
                0.0,
                1.0,
            );
            let specular = mixf(1.0, 0.06, land_amount);
            color_row[column] = pack(
                to_byte(emission.sqrt()),
                to_byte(albedo[0]),
                to_byte(albedo[1]),
                to_byte(albedo[2]),
            );
            surface_row[column] = pack(
                to_byte(cloud),
                to_byte(0.5 + 0.5 * clampf(slope_east, -1.0, 1.0)),
                to_byte(0.5 + 0.5 * clampf(slope_north, -1.0, 1.0)),
                to_byte(specular),
            );
        }
    });
    0
}

#[cfg(not(all(
    target_arch = "x86_64",
    target_feature = "avx2",
    target_feature = "fma"
)))]
fn render_interior(frame: &Frame, row: &mut Row, start: usize, end: usize) {
    frame.render_span::<true, false>(row, start, end);
}

#[cfg(all(
    target_arch = "x86_64",
    target_feature = "avx2",
    target_feature = "fma"
))]
fn render_interior(frame: &Frame, row: &mut Row, start: usize, end: usize) {
    unsafe { wide::render_interior(frame, row, start, end) }
}

#[cfg(all(
    target_arch = "x86_64",
    target_feature = "avx2",
    target_feature = "fma"
))]
mod wide {
    use super::{Frame, GRADE_STEPS, POLE_TEXELS, Row, WRAP_BIAS_TEXELS};
    use std::arch::x86_64::*;

    struct Taps8 {
        top_left: __m256i,
        top_right: __m256i,
        bottom_left: __m256i,
        bottom_right: __m256i,
        weight_x: __m256i,
        weight_y: __m256i,
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn splat(value: f32) -> __m256 {
        _mm256_set1_ps(value)
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn splat_int(value: i32) -> __m256i {
        _mm256_set1_epi32(value)
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn clamp8(value: __m256, low: f32, high: f32) -> __m256 {
        _mm256_min_ps(_mm256_max_ps(value, splat(low)), splat(high))
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn smoothstep8(edge0: f32, edge1: f32, value: __m256) -> __m256 {
        let t = clamp8(
            _mm256_mul_ps(
                _mm256_sub_ps(value, splat(edge0)),
                splat(1.0 / (edge1 - edge0)),
            ),
            0.0,
            1.0,
        );
        _mm256_mul_ps(
            _mm256_mul_ps(t, t),
            _mm256_fnmadd_ps(splat(2.0), t, splat(3.0)),
        )
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn mix8(first: __m256, second: __m256, amount: __m256) -> __m256 {
        _mm256_fmadd_ps(_mm256_sub_ps(second, first), amount, first)
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn byte8(pixel: __m256i, shift: i32) -> __m256 {
        _mm256_cvtepi32_ps(_mm256_and_si256(
            _mm256_srlv_epi32(pixel, splat_int(shift)),
            splat_int(0xFF),
        ))
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn blend8(first: __m256i, second: __m256i, weight: __m256i) -> __m256i {
        let mask = splat_int(0x00FF00FF);
        let weights = _mm256_or_si256(weight, _mm256_slli_epi32::<16>(weight));
        let inverse = _mm256_sub_epi16(_mm256_set1_epi16(256), weights);
        let red_blue = _mm256_srli_epi16::<8>(_mm256_add_epi16(
            _mm256_mullo_epi16(_mm256_and_si256(first, mask), inverse),
            _mm256_mullo_epi16(_mm256_and_si256(second, mask), weights),
        ));
        let alpha_green = _mm256_andnot_si256(
            mask,
            _mm256_add_epi16(
                _mm256_mullo_epi16(
                    _mm256_and_si256(_mm256_srli_epi32::<8>(first), mask),
                    inverse,
                ),
                _mm256_mullo_epi16(
                    _mm256_and_si256(_mm256_srli_epi32::<8>(second), mask),
                    weights,
                ),
            ),
        );
        _mm256_or_si256(red_blue, alpha_green)
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn taps8(frame: &Frame, level: __m256i, u: __m256, v: __m256) -> Taps8 {
        let one = splat_int(1);
        let texels = frame.base_width * frame.base_height;
        let width_shift =
            _mm256_sub_epi32(splat_int(frame.base_width.trailing_zeros() as i32), level);
        let width_mask = _mm256_sub_epi32(_mm256_sllv_epi32(one, width_shift), one);
        let last_row =
            _mm256_sub_epi32(_mm256_srlv_epi32(splat_int(frame.base_height), level), one);
        let remaining = _mm256_srlv_epi32(splat_int(texels), _mm256_add_epi32(level, level));
        let offset = _mm256_cvtps_epi32(_mm256_mul_ps(
            _mm256_cvtepi32_ps(_mm256_sub_epi32(splat_int(texels), remaining)),
            splat(4.0 / 3.0),
        ));
        let scale = _mm256_castsi256_ps(_mm256_slli_epi32::<23>(_mm256_sub_epi32(
            splat_int(127),
            level,
        )));
        let half = splat(0.5);
        let fu = _mm256_fmsub_ps(u, scale, half);
        let fv = _mm256_min_ps(
            _mm256_max_ps(_mm256_fmsub_ps(v, scale, half), _mm256_setzero_ps()),
            _mm256_cvtepi32_ps(last_row),
        );
        let ix = _mm256_cvttps_epi32(_mm256_mul_ps(
            _mm256_add_ps(fu, splat(WRAP_BIAS_TEXELS)),
            splat(256.0),
        ));
        let iy = _mm256_cvttps_epi32(_mm256_mul_ps(fv, splat(256.0)));
        let x0 = _mm256_and_si256(_mm256_srli_epi32::<8>(ix), width_mask);
        let x1 = _mm256_and_si256(_mm256_add_epi32(x0, one), width_mask);
        let y0 = _mm256_srli_epi32::<8>(iy);
        let y1 = _mm256_min_epi32(_mm256_add_epi32(y0, one), last_row);
        let top = _mm256_add_epi32(offset, _mm256_sllv_epi32(y0, width_shift));
        let bottom = _mm256_add_epi32(offset, _mm256_sllv_epi32(y1, width_shift));
        Taps8 {
            top_left: _mm256_add_epi32(top, x0),
            top_right: _mm256_add_epi32(top, x1),
            bottom_left: _mm256_add_epi32(bottom, x0),
            bottom_right: _mm256_add_epi32(bottom, x1),
            weight_x: _mm256_and_si256(ix, splat_int(0xFF)),
            weight_y: _mm256_and_si256(iy, splat_int(0xFF)),
        }
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    unsafe fn gather8(texels: &[u32], index: __m256i) -> __m256i {
        unsafe { _mm256_i32gather_epi32::<4>(texels.as_ptr().cast(), index) }
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    unsafe fn fetch8(texels: &[u32], taps: &Taps8) -> __m256i {
        unsafe {
            blend8(
                blend8(
                    gather8(texels, taps.top_left),
                    gather8(texels, taps.top_right),
                    taps.weight_x,
                ),
                blend8(
                    gather8(texels, taps.bottom_left),
                    gather8(texels, taps.bottom_right),
                    taps.weight_x,
                ),
                taps.weight_y,
            )
        }
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    unsafe fn cloud_texel8(texels: &[u32], index: __m256i) -> __m256 {
        unsafe { _mm256_mul_ps(byte8(gather8(texels, index), 24), splat(1.0 / 255.0)) }
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn tone_map8(value: __m256) -> __m256 {
        let value = _mm256_max_ps(value, _mm256_setzero_ps());
        let numerator = _mm256_mul_ps(value, _mm256_fmadd_ps(value, splat(2.51), splat(0.03)));
        let denominator = _mm256_fmadd_ps(
            value,
            _mm256_fmadd_ps(value, splat(2.43), splat(0.59)),
            splat(0.14),
        );
        _mm256_min_ps(_mm256_div_ps(numerator, denominator), splat(1.0))
    }

    #[inline]
    #[target_feature(enable = "avx2,fma")]
    fn dot8(x: __m256, y: __m256, z: __m256, direction: [f32; 3]) -> __m256 {
        _mm256_fmadd_ps(
            x,
            splat(direction[0]),
            _mm256_fmadd_ps(
                y,
                splat(direction[1]),
                _mm256_mul_ps(z, splat(direction[2])),
            ),
        )
    }

    #[target_feature(enable = "avx2,fma")]
    pub(super) fn render_interior(frame: &Frame, row: &mut Row, start: usize, end: usize) {
        let zero = _mm256_setzero_ps();
        let one = splat(1.0);
        let last_level = splat_int(frame.last_level);
        let lanes = _mm256_setr_ps(0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5);
        let lane_offsets = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
        let sy = splat(row.sy);
        let cos_pitch = splat(frame.cos_pitch);
        let sin_pitch = splat(frame.sin_pitch);
        let inverse_255 = splat(1.0 / 255.0);
        let inverse_256 = splat(1.0 / 256.0);
        let texture_height = splat(frame.texture_height);
        let row_hash = splat_int(row.index.wrapping_mul(0xd8163841) as i32);
        let mut column = start;
        while column + 8 <= end {
            unsafe {
                let sx = _mm256_mul_ps(
                    _mm256_sub_ps(
                        _mm256_add_ps(splat(column as f32), lanes),
                        splat(frame.center),
                    ),
                    splat(frame.inverse_radius),
                );
                let distance_squared = _mm256_fmadd_ps(sx, sx, _mm256_mul_ps(sy, sy));
                let sz = _mm256_sqrt_ps(_mm256_max_ps(_mm256_sub_ps(one, distance_squared), zero));

                let base_u = _mm256_loadu_ps(row.u.as_ptr().add(column));
                let pixel_u = _mm256_add_ps(base_u, splat(frame.shift));
                let pixel_v = _mm256_loadu_ps(row.v.as_ptr().add(column));
                let pixel_lod = _mm256_loadu_ps(row.lod.as_ptr().add(column));
                let level = _mm256_min_epi32(_mm256_cvttps_epi32(pixel_lod), last_level);
                let next_level =
                    _mm256_min_epi32(_mm256_add_epi32(level, splat_int(1)), last_level);
                let mip_weight = _mm256_cvttps_epi32(_mm256_mul_ps(
                    clamp8(
                        _mm256_sub_ps(pixel_lod, _mm256_cvtepi32_ps(level)),
                        0.0,
                        1.0,
                    ),
                    splat(256.0),
                ));
                let taps = taps8(frame, level, pixel_u, pixel_v);
                let mut color = fetch8(frame.color_source, &taps);
                let mut surface = fetch8(frame.surface_source, &taps);
                let taps = taps8(frame, next_level, pixel_u, pixel_v);
                color = blend8(color, fetch8(frame.color_source, &taps), mip_weight);
                surface = blend8(surface, fetch8(frame.surface_source, &taps), mip_weight);
                let pole_distance = _mm256_min_ps(pixel_v, _mm256_sub_ps(texture_height, pixel_v));
                let pole_weight = _mm256_cvttps_epi32(_mm256_mul_ps(
                    clamp8(
                        _mm256_fnmadd_ps(pole_distance, splat(1.0 / POLE_TEXELS), one),
                        0.0,
                        1.0,
                    ),
                    splat(256.0),
                ));
                let north = _mm256_castps_si256(_mm256_cmp_ps::<_CMP_LT_OQ>(
                    pixel_v,
                    _mm256_mul_ps(texture_height, splat(0.5)),
                ));
                color = blend8(
                    color,
                    _mm256_blendv_epi8(
                        splat_int(frame.color_poles[1] as i32),
                        splat_int(frame.color_poles[0] as i32),
                        north,
                    ),
                    pole_weight,
                );
                surface = blend8(
                    surface,
                    _mm256_blendv_epi8(
                        splat_int(frame.surface_poles[1] as i32),
                        splat_int(frame.surface_poles[0] as i32),
                        north,
                    ),
                    pole_weight,
                );

                let cloud_level = _mm256_min_epi32(
                    _mm256_cvttps_epi32(_mm256_add_ps(pixel_lod, splat(1.5))),
                    last_level,
                );
                let taps = taps8(
                    frame,
                    cloud_level,
                    _mm256_add_ps(base_u, splat(frame.cloud_shift)),
                    pixel_v,
                );
                let cloud_top_left = cloud_texel8(frame.surface_source, taps.top_left);
                let cloud_top_right = cloud_texel8(frame.surface_source, taps.top_right);
                let cloud_bottom_left = cloud_texel8(frame.surface_source, taps.bottom_left);
                let cloud_bottom_right = cloud_texel8(frame.surface_source, taps.bottom_right);
                let cloud_x = _mm256_mul_ps(_mm256_cvtepi32_ps(taps.weight_x), inverse_256);
                let cloud_y = _mm256_mul_ps(_mm256_cvtepi32_ps(taps.weight_y), inverse_256);
                let cloud = mix8(
                    mix8(cloud_top_left, cloud_top_right, cloud_x),
                    mix8(cloud_bottom_left, cloud_bottom_right, cloud_x),
                    cloud_y,
                );
                let shadow_x = clamp8(
                    _mm256_sub_ps(cloud_x, splat(frame.shadow_shift_x)),
                    0.0,
                    1.0,
                );
                let shadow_y = clamp8(
                    _mm256_add_ps(cloud_y, splat(frame.shadow_shift_y)),
                    0.0,
                    1.0,
                );
                let cloud_shadow = mix8(
                    mix8(cloud_top_left, cloud_top_right, shadow_x),
                    mix8(cloud_bottom_left, cloud_bottom_right, shadow_x),
                    shadow_y,
                );

                let world_y = _mm256_fmadd_ps(sy, cos_pitch, _mm256_mul_ps(sz, sin_pitch));
                let world_z = _mm256_fmsub_ps(sz, cos_pitch, _mm256_mul_ps(sy, sin_pitch));
                let latitude_cos =
                    _mm256_sqrt_ps(_mm256_fmadd_ps(sx, sx, _mm256_mul_ps(world_z, world_z)));
                let inverse_cos = _mm256_div_ps(one, _mm256_max_ps(latitude_cos, splat(1e-4)));
                let east_x = _mm256_mul_ps(world_z, inverse_cos);
                let east_world_z = _mm256_mul_ps(_mm256_sub_ps(zero, sx), inverse_cos);
                let east_y = _mm256_mul_ps(_mm256_sub_ps(zero, east_world_z), sin_pitch);
                let east_z = _mm256_mul_ps(east_world_z, cos_pitch);
                let north_x =
                    _mm256_mul_ps(_mm256_mul_ps(_mm256_sub_ps(zero, world_y), sx), inverse_cos);
                let north_world_z = _mm256_mul_ps(
                    _mm256_mul_ps(_mm256_sub_ps(zero, world_y), world_z),
                    inverse_cos,
                );
                let north_y = _mm256_fnmadd_ps(
                    north_world_z,
                    sin_pitch,
                    _mm256_mul_ps(latitude_cos, cos_pitch),
                );
                let north_z = _mm256_fmadd_ps(
                    north_world_z,
                    cos_pitch,
                    _mm256_mul_ps(latitude_cos, sin_pitch),
                );
                let bump = splat(frame.bump);
                let slope_east =
                    _mm256_mul_ps(_mm256_sub_ps(byte8(surface, 16), splat(128.0)), bump);
                let slope_north =
                    _mm256_mul_ps(_mm256_sub_ps(byte8(surface, 8), splat(128.0)), bump);
                let inverse_length = _mm256_div_ps(
                    one,
                    _mm256_sqrt_ps(_mm256_fmadd_ps(
                        slope_east,
                        slope_east,
                        _mm256_fmadd_ps(slope_north, slope_north, one),
                    )),
                );
                let bumped_x = _mm256_mul_ps(
                    _mm256_fnmadd_ps(
                        slope_north,
                        north_x,
                        _mm256_fnmadd_ps(slope_east, east_x, sx),
                    ),
                    inverse_length,
                );
                let bumped_y = _mm256_mul_ps(
                    _mm256_fnmadd_ps(
                        slope_north,
                        north_y,
                        _mm256_fnmadd_ps(slope_east, east_y, sy),
                    ),
                    inverse_length,
                );
                let bumped_z = _mm256_mul_ps(
                    _mm256_fnmadd_ps(
                        slope_north,
                        north_z,
                        _mm256_fnmadd_ps(slope_east, east_z, sz),
                    ),
                    inverse_length,
                );

                let geometric = dot8(sx, sy, sz, frame.light);
                let facing = dot8(bumped_x, bumped_y, bumped_z, frame.light);
                let diffuse = _mm256_mul_ps(
                    clamp8(
                        _mm256_mul_ps(_mm256_add_ps(facing, splat(0.3)), splat(1.0 / 1.3)),
                        0.0,
                        1.0,
                    ),
                    smoothstep8(-0.3, 0.15, geometric),
                );
                let daylight = smoothstep8(-0.12, 0.32, geometric);
                let band_distance =
                    _mm256_mul_ps(_mm256_sub_ps(geometric, splat(0.03)), splat(1.0 / 0.24));
                let band = _mm256_mul_ps(
                    splat(frame.warm_amount),
                    clamp8(
                        _mm256_fnmadd_ps(band_distance, band_distance, one),
                        0.0,
                        1.0,
                    ),
                );
                let rim = clamp8(dot8(bumped_x, bumped_y, bumped_z, frame.rim), 0.0, 1.0);
                let sky = _mm256_fmadd_ps(bumped_y, splat(0.5), splat(0.5));
                let mut half_facing =
                    clamp8(dot8(bumped_x, bumped_y, bumped_z, frame.half), 0.0, 1.0);
                half_facing = _mm256_and_ps(
                    half_facing,
                    _mm256_cmp_ps::<_CMP_GT_OQ>(half_facing, splat(0.3)),
                );
                let mut broad = _mm256_mul_ps(half_facing, half_facing);
                broad = _mm256_mul_ps(broad, broad);
                broad = _mm256_mul_ps(broad, broad);
                let mut glossy = _mm256_mul_ps(broad, broad);
                glossy = _mm256_mul_ps(glossy, glossy);
                glossy = _mm256_mul_ps(glossy, glossy);
                let grazing = _mm256_sub_ps(one, sz);
                let grazing_squared = _mm256_mul_ps(grazing, grazing);
                let fresnel = _mm256_fmadd_ps(
                    _mm256_mul_ps(_mm256_mul_ps(grazing_squared, grazing_squared), grazing),
                    splat(0.96),
                    splat(0.04),
                );
                let mut specular = _mm256_mul_ps(
                    _mm256_mul_ps(byte8(surface, 0), inverse_255),
                    _mm256_sub_ps(one, cloud),
                );
                specular = _mm256_mul_ps(specular, _mm256_fmadd_ps(broad, splat(0.03), glossy));
                specular = _mm256_mul_ps(
                    _mm256_mul_ps(specular, _mm256_fmadd_ps(fresnel, splat(4.0), one)),
                    daylight,
                );
                let shadow =
                    _mm256_fnmadd_ps(_mm256_mul_ps(splat(0.45), cloud_shadow), daylight, one);
                let mut emissive = _mm256_mul_ps(byte8(color, 24), inverse_255);
                let night = _mm256_sub_ps(one, daylight);
                emissive = _mm256_mul_ps(
                    _mm256_mul_ps(emissive, emissive),
                    _mm256_mul_ps(
                        _mm256_mul_ps(night, night),
                        _mm256_fnmadd_ps(splat(0.6), cloud, one),
                    ),
                );
                let haze = _mm256_mul_ps(
                    grazing_squared,
                    _mm256_fmadd_ps(grazing, splat(0.25), splat(0.35)),
                );
                let haze_light = _mm256_fmadd_ps(
                    clamp8(_mm256_add_ps(geometric, splat(0.25)), 0.0, 1.0),
                    splat(1.1),
                    splat(0.25),
                );
                let haze_mix = smoothstep8(-0.35, 0.5, geometric);
                let haze_keep = _mm256_fnmadd_ps(haze, splat(0.6), one);
                let cloud_amount = _mm256_mul_ps(cloud, splat(0.8));
                let lit_light = _mm256_mul_ps(diffuse, shadow);

                let column_index = _mm256_add_epi32(splat_int(column as i32), lane_offsets);
                let mut hash = _mm256_xor_si256(
                    _mm256_xor_si256(
                        _mm256_mullo_epi32(column_index, splat_int(0x8da6b343u32 as i32)),
                        row_hash,
                    ),
                    splat_int(frame.grain_seed as i32),
                );
                hash = _mm256_xor_si256(hash, _mm256_srli_epi32::<15>(hash));
                hash = _mm256_mullo_epi32(hash, splat_int(0x2c1b3c6d));
                hash = _mm256_xor_si256(hash, _mm256_srli_epi32::<12>(hash));
                let dither = _mm256_mul_ps(
                    _mm256_fmsub_ps(
                        _mm256_cvtepi32_ps(_mm256_and_si256(hash, splat_int(0xFFFF))),
                        splat(1.0 / 32767.5),
                        one,
                    ),
                    splat(frame.grain_amount),
                );

                let bloom_position =
                    _mm256_fmsub_ps(_mm256_cvtepi32_ps(column_index), splat(0.25), splat(0.375));
                let mut bloom_left = _mm256_cvttps_epi32(_mm256_floor_ps(bloom_position));
                let bloom_weight = _mm256_sub_ps(bloom_position, _mm256_cvtepi32_ps(bloom_left));
                let mut bloom_right = _mm256_min_epi32(
                    _mm256_add_epi32(bloom_left, splat_int(1)),
                    splat_int(frame.quarter as i32 - 1),
                );
                bloom_left = _mm256_max_epi32(bloom_left, _mm256_setzero_si256());
                bloom_left = _mm256_add_epi32(bloom_left, _mm256_add_epi32(bloom_left, bloom_left));
                bloom_right =
                    _mm256_add_epi32(bloom_right, _mm256_add_epi32(bloom_right, bloom_right));

                let mut packed = splat_int(0xFF000000u32 as i32);
                let mut bright_packed = _mm256_setzero_si256();
                for component in 0..3 {
                    let shift = 16 - 8 * component as i32;
                    let offset = splat_int(component as i32);
                    let glow = mix8(
                        _mm256_i32gather_ps::<4>(
                            row.glow.as_ptr(),
                            _mm256_add_epi32(bloom_left, offset),
                        ),
                        _mm256_i32gather_ps::<4>(
                            row.glow.as_ptr(),
                            _mm256_add_epi32(bloom_right, offset),
                        ),
                        bloom_weight,
                    );
                    let encoded = _mm256_mul_ps(byte8(color, shift), inverse_255);
                    let albedo = _mm256_mul_ps(
                        encoded,
                        _mm256_fmadd_ps(
                            encoded,
                            _mm256_fmadd_ps(encoded, splat(0.305_306), splat(0.682_171_1)),
                            splat(0.012522878),
                        ),
                    );
                    let light = mix8(
                        splat(frame.key[component]),
                        splat(frame.warm[component]),
                        band,
                    );
                    let ambient = mix8(
                        splat(frame.ground_ambient[component]),
                        splat(frame.sky_ambient[component]),
                        sky,
                    );
                    let mut lit = _mm256_fmadd_ps(
                        albedo,
                        _mm256_fmadd_ps(light, lit_light, ambient),
                        _mm256_mul_ps(splat(frame.rim_color[component]), rim),
                    );
                    let cloud_lit = _mm256_mul_ps(
                        splat(frame.cloud_color[component]),
                        _mm256_fmadd_ps(light, diffuse, _mm256_mul_ps(ambient, splat(1.6))),
                    );
                    lit = mix8(lit, cloud_lit, cloud_amount);
                    let specular_light = _mm256_mul_ps(specular, light);
                    let emission = _mm256_mul_ps(emissive, splat(frame.emissive_color[component]));
                    lit = _mm256_add_ps(lit, _mm256_add_ps(specular_light, emission));
                    let atmosphere = _mm256_mul_ps(
                        mix8(
                            splat(frame.atmosphere_dark[component]),
                            splat(frame.atmosphere_lit[component]),
                            haze_mix,
                        ),
                        haze_light,
                    );
                    let planet = _mm256_mul_ps(
                        _mm256_add_ps(
                            _mm256_fmadd_ps(lit, haze_keep, _mm256_mul_ps(atmosphere, haze)),
                            glow,
                        ),
                        splat(frame.exposure),
                    );
                    let grade_index = _mm256_cvttps_epi32(_mm256_mul_ps(
                        tone_map8(planet),
                        splat(GRADE_STEPS as f32),
                    ));
                    let value = _mm256_add_ps(
                        _mm256_i32gather_ps::<4>(
                            frame.tables.grade[component].as_ptr(),
                            grade_index,
                        ),
                        dither,
                    );
                    let channel_value =
                        _mm256_cvttps_epi32(clamp8(_mm256_add_ps(value, splat(0.5)), 0.0, 255.0));
                    packed =
                        _mm256_or_si256(packed, _mm256_sllv_epi32(channel_value, splat_int(shift)));
                    let bright_value = _mm256_sub_ps(
                        _mm256_add_ps(specular_light, emission),
                        splat(frame.bloom_threshold),
                    );
                    let bright_channel = _mm256_cvttps_epi32(clamp8(
                        _mm256_mul_ps(bright_value, splat(super::BRIGHT_SCALE)),
                        0.0,
                        255.0,
                    ));
                    bright_packed = _mm256_or_si256(
                        bright_packed,
                        _mm256_sllv_epi32(bright_channel, splat_int(shift)),
                    );
                }
                _mm256_storeu_si256(row.line.as_mut_ptr().add(column).cast(), packed);
                _mm256_storeu_si256(row.bright.as_mut_ptr().add(column).cast(), bright_packed);
            }
            column += 8;
        }
        frame.render_span::<true, false>(row, column, end);
    }
}
