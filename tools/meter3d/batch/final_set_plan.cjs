'use strict';
// batch/final_set_plan.cjs - Exact specification plan generator for the 294-frame final synthetic test set.

const assert = require('node:assert/strict');
const DISTRACTOR_KINDS = {
  dual_scale: 'dual_scale', non_scale_numbers: 'non_scale_number',
  extra_labels: 'extra_label', danger_band_numbers: 'danger_band_number'
};

function validateFrame(item, truth, rawExport = false, distance = truth.applied_params?.distance ?? 5.6) {
  const active = Object.entries(item.round2).filter(([k, v]) => k !== 'seed' && v > 0);
  const expected = Object.fromEntries(active
    .filter(([k]) => rawExport || !Object.hasOwn(DISTRACTOR_KINDS, k))
    .map(([k, strength]) => [k, { strength, seed: item.round2.seed }]));
  assert.deepStrictEqual(truth.degradations, expected, `${item.id}: degradations differ from plan`);
  const kinds = active.filter(([k]) => Object.hasOwn(DISTRACTOR_KINDS, k)).map(([k]) => DISTRACTOR_KINDS[k]);
  assert.deepStrictEqual([...new Set(truth.distractors.map(d => d.kind))].sort(), kinds.sort(), `${item.id}: distractor kinds differ from plan`);
  assert.equal(truth.seed, item.round2.seed, `${item.id}: seed differs from plan`);
  for (const [k, v] of Object.entries(item.appearance)) assert.equal(truth.appearance[k], v, `${item.id}: appearance.${k}`);
  assert.equal(truth.camera.yaw_deg, item.cam.yaw, `${item.id}: camera yaw`);
  assert.equal(truth.camera.pitch_deg, item.cam.pitch, `${item.id}: camera pitch`);
  assert.equal(truth.camera.distance, Number((distance + (item.round2.small_in_frame || 0) * 7.5).toFixed(6)), `${item.id}: camera distance`);
  const light = item.lightingParams || { light_azimuth_deg: -35, light_elevation_deg: 45, light_intensity: 1.2, glass_reflection: 0.2 };
  assert.deepStrictEqual(truth.light, { azimuth_deg: light.light_azimuth_deg, elevation_deg: light.light_elevation_deg, intensity: light.light_intensity }, `${item.id}: lighting`);
  assert.equal(truth.glass_reflection, light.glass_reflection, `${item.id}: glass reflection`);
  if (truth.condition) {
    for (const [k, v] of Object.entries(item.condition)) assert.equal(truth.condition[k], v, `${item.id}: condition.${k}`);
  }
}

const METER_DEFS = {
  'pressure-150': { meter_type: 'pressure', range: '150', min: 0, max: 150, prefix: 'p150' },
  'pressure-400': { meter_type: 'pressure', range: '400', min: 0, max: 400, prefix: 'p400' },
  'temperature-100': { meter_type: 'temperature', range: '100', min: 0, max: 100, prefix: 't100' },
  'pressure-1.0': { meter_type: 'pressure', range: '1.0', min: 0, max: 1, prefix: 'p1' },
  'pressure-1.6': { meter_type: 'pressure', range: '1.6', min: 0, max: 1.6, prefix: 'p1_6' },
  'pressure-250': { meter_type: 'pressure', range: '250', min: 0, max: 250, prefix: 'p250' },
  'pressure-16': { meter_type: 'pressure', range: '16', min: 0, max: 16, prefix: 'p16' },
  'pressure--0.1:0.5': { meter_type: 'pressure', range: '-0.1:0.5', min: -0.1, max: 0.5, prefix: 'pneg' },
  'temperature-60': { meter_type: 'temperature', range: '60', min: 0, max: 60, prefix: 't60' },
  'temperature--20:120': { meter_type: 'temperature', range: '-20:120', min: -20, max: 120, prefix: 'tneg' }
};

const RANGES_ORDER = [
  'pressure-150',
  'pressure-400',
  'temperature-100',
  'pressure-1.0',
  'pressure-1.6',
  'pressure-250',
  'pressure-16',
  'pressure--0.1:0.5',
  'temperature-60',
  'temperature--20:120'
];

// Well-distributed non-round percentages across 0..100
const NON_ROUND_PCTS = [7, 14, 23, 27, 36, 42, 48, 53, 59, 64, 71, 78, 84, 93];

function makeAppearance(index, override = {}) {
  const sweep_deg = [270, 240, 300][index % 3];
  const dial_color = ['white', 'black', 'cream'][Math.floor(index / 2) % 3];
  const number_position = ['inside', 'outside'][index % 2];
  const font = ['sans', 'serif', 'mono'][Math.floor(index / 3) % 3];
  const needle_shape = ['lance', 'arrow', 'counterweight'][(index + 1) % 3];
  const needle_color = ['black', 'red'][(index + Math.floor(index / 6)) % 2];
  const bezel_color = ['black', 'silver', 'brass'][(index + 2) % 3];
  const danger_band = (index % 4 === 1 || index % 4 === 3);
  const max_pointer = (index % 5 === 2 || index % 5 === 4);
  return {
    sweep_deg,
    dial_color,
    number_position,
    font,
    needle_shape,
    needle_color,
    bezel_color,
    danger_band,
    max_pointer,
    ...override
  };
}

function buildFinalSetPlan() {
  const plan = [];
  const plannedIds = new Set();
  let seedCounter = 1000;

  function addItem(item) {
    if (plannedIds.has(item.id)) {
      throw new Error(`Duplicate frame ID detected in final set plan: ${item.id}`);
    }
    plannedIds.add(item.id);
    plan.push(item);
  }

  // 1. 正面: all 10 ranges x 3 values x 2 appearance variants, yaw 0 pitch 0, normal light, no degradations -> 60
  for (let rIdx = 0; rIdx < RANGES_ORDER.length; rIdx++) {
    const meterKey = RANGES_ORDER[rIdx];
    const prefix = METER_DEFS[meterKey].prefix;
    // 3 non-round values for this range
    const vPcts = [
      NON_ROUND_PCTS[(rIdx * 3 + 0) % NON_ROUND_PCTS.length],
      NON_ROUND_PCTS[(rIdx * 3 + 1) % NON_ROUND_PCTS.length],
      NON_ROUND_PCTS[(rIdx * 3 + 2) % NON_ROUND_PCTS.length]
    ];
    for (let vIdx = 0; vIdx < vPcts.length; vIdx++) {
      const pct = vPcts[vIdx];
      for (let varIdx = 0; varIdx < 2; varIdx++) {
        const id = `${prefix}_v${String(pct).padStart(2, '0')}_var${varIdx + 1}_正面`;
        const appearance = makeAppearance(rIdx * 6 + vIdx * 2 + varIdx, {
          danger_band: varIdx === 0,
          max_pointer: varIdx === 1
        });
        addItem({
          meterKey,
          pct,
          cam: { yaw: 0, pitch: 0 },
          lighting: 'normal',
          id,
          subfolder: '正面',
          appearance,
          round2: { seed: ++seedCounter },
          condition: {
            meter_id: meterKey,
            value_percent: pct,
            camera_yaw: 0,
            camera_pitch: 0,
            lighting: 'normal',
            blur: 'none',
            category: '正面',
            appearance_variant: varIdx + 1
          }
        });
      }
    }
  }

  // 2. 斜め: 10 ranges x yaw {15, 30, 45, 60} at pitch 0 (one value each) -> 40, plus 10 ranges x pitch 25 yaw 0 -> 10; total 50
  const yawAngles = [15, 30, 45, 60];
  for (let rIdx = 0; rIdx < RANGES_ORDER.length; rIdx++) {
    const meterKey = RANGES_ORDER[rIdx];
    const prefix = METER_DEFS[meterKey].prefix;
    for (let yIdx = 0; yIdx < yawAngles.length; yIdx++) {
      const yaw = yawAngles[yIdx];
      const pct = NON_ROUND_PCTS[(rIdx * 4 + yIdx) % NON_ROUND_PCTS.length];
      const id = `${prefix}_v${String(pct).padStart(2, '0')}_y${yaw}p0_斜め`;
      const appearance = makeAppearance(60 + rIdx * 4 + yIdx);
      addItem({
        meterKey,
        pct,
        cam: { yaw, pitch: 0 },
        lighting: 'normal',
        id,
        subfolder: '斜め',
        appearance,
        round2: { seed: ++seedCounter },
        condition: {
          meter_id: meterKey,
          value_percent: pct,
          camera_yaw: yaw,
          camera_pitch: 0,
          lighting: 'normal',
          blur: 'none',
          category: '斜め'
        }
      });
    }
  }
  for (let rIdx = 0; rIdx < RANGES_ORDER.length; rIdx++) {
    const meterKey = RANGES_ORDER[rIdx];
    const prefix = METER_DEFS[meterKey].prefix;
    const pct = NON_ROUND_PCTS[(rIdx * 3 + 5) % NON_ROUND_PCTS.length];
    const id = `${prefix}_v${String(pct).padStart(2, '0')}_y0p25_斜め`;
    const appearance = makeAppearance(100 + rIdx);
    addItem({
      meterKey,
      pct,
      cam: { yaw: 0, pitch: 25 },
      lighting: 'normal',
      id,
      subfolder: '斜め',
      appearance,
      round2: { seed: ++seedCounter },
      condition: {
        meter_id: meterKey,
        value_percent: pct,
        camera_yaw: 0,
        camera_pitch: 25,
        lighting: 'normal',
        blur: 'none',
        category: '斜め'
      }
    });
  }

  // 3. 反射: 10 ranges x glare levels {glass_reflection 0.5/intensity 1.8, 0.75/2.2, 0.95/2.6} with highlight crossing dial -> 30
  const glareLevels = [
    { ref: 0.5, int: 1.8, tag: 'g050' },
    { ref: 0.75, int: 2.2, tag: 'g075' },
    { ref: 0.95, int: 2.6, tag: 'g095' }
  ];
  for (let rIdx = 0; rIdx < RANGES_ORDER.length; rIdx++) {
    const meterKey = RANGES_ORDER[rIdx];
    const prefix = METER_DEFS[meterKey].prefix;
    for (let gIdx = 0; gIdx < glareLevels.length; gIdx++) {
      const g = glareLevels[gIdx];
      const pct = NON_ROUND_PCTS[(rIdx * 3 + gIdx) % NON_ROUND_PCTS.length];
      const id = `${prefix}_v${String(pct).padStart(2, '0')}_${g.tag}_反射`;
      const appearance = makeAppearance(110 + rIdx * 3 + gIdx);
      addItem({
        meterKey,
        pct,
        cam: { yaw: 0, pitch: 0 },
        lighting: 'glare',
        lightingParams: {
          light_azimuth_deg: 15,
          light_elevation_deg: 8,
          light_intensity: g.int,
          glass_reflection: g.ref
        },
        id,
        subfolder: '反射',
        appearance,
        round2: { seed: ++seedCounter },
        condition: {
          meter_id: meterKey,
          value_percent: pct,
          camera_yaw: 0,
          camera_pitch: 0,
          lighting: `glare_${g.tag}`,
          glass_reflection: g.ref,
          light_intensity: g.int,
          blur: 'none',
          category: '反射'
        }
      });
    }
  }

  // 4. ブレ: 10 ranges x motion blur {7, 15, 25 px} (clean frontal frames, horizontal blur postprocess) -> 30
  const blurWidths = [7, 15, 25];
  for (let rIdx = 0; rIdx < RANGES_ORDER.length; rIdx++) {
    const meterKey = RANGES_ORDER[rIdx];
    const prefix = METER_DEFS[meterKey].prefix;
    for (let bIdx = 0; bIdx < blurWidths.length; bIdx++) {
      const bWidth = blurWidths[bIdx];
      const pct = NON_ROUND_PCTS[(rIdx * 3 + bIdx) % NON_ROUND_PCTS.length];
      const id = `${prefix}_v${String(pct).padStart(2, '0')}_b${String(bWidth).padStart(2, '0')}_ブレ`;
      const appearance = makeAppearance(140 + rIdx * 3 + bIdx);
      addItem({
        meterKey,
        pct,
        cam: { yaw: 0, pitch: 0 },
        lighting: 'normal',
        lightingParams: {
          light_azimuth_deg: -35,
          light_elevation_deg: 45,
          light_intensity: 1.2,
          glass_reflection: 0.2
        },
        targetBlurWidth: bWidth,
        id,
        subfolder: 'ブレ',
        appearance,
        round2: { seed: ++seedCounter },
        condition: {
          meter_id: meterKey,
          value_percent: pct,
          camera_yaw: 0,
          camera_pitch: 0,
          lighting: 'normal',
          blur: `motion${bWidth}`,
          target_blur_width: bWidth,
          category: 'ブレ'
        }
      });
    }
  }

  // 5. 汚れ: {dial_yellowing, dial_dirt, faded_print, glass_scratches, glass_fog, glass_droplets} x {0.3, 0.6, 0.9} x 2 ranges -> 36
  const dirtKeys = ['dial_yellowing', 'dial_dirt', 'faded_print', 'glass_scratches', 'glass_fog', 'glass_droplets'];
  const dirtStrengths = [0.3, 0.6, 0.9];
  let dirtComboIdx = 0;
  for (const dKey of dirtKeys) {
    for (const dStr of dirtStrengths) {
      for (let rep = 0; rep < 2; rep++) {
        const rIdx = (dirtComboIdx * 2 + rep) % RANGES_ORDER.length;
        const meterKey = RANGES_ORDER[rIdx];
        const prefix = METER_DEFS[meterKey].prefix;
        const pct = NON_ROUND_PCTS[(dirtComboIdx * 2 + rep) % NON_ROUND_PCTS.length];
        const sLabel = String(Math.round(dStr * 100)).padStart(2, '0');
        const id = `${prefix}_v${String(pct).padStart(2, '0')}_${dKey}_s${sLabel}_r${rep + 1}_汚れ`;
        const appearance = makeAppearance(170 + dirtComboIdx * 2 + rep);
        addItem({
          meterKey,
          pct,
          cam: { yaw: 0, pitch: 0 },
          lighting: 'normal',
          id,
          subfolder: '汚れ',
          appearance,
          round2: { seed: ++seedCounter, [dKey]: dStr },
          condition: {
            meter_id: meterKey,
            value_percent: pct,
            camera_yaw: 0,
            camera_pitch: 0,
            lighting: 'normal',
            blur: 'none',
            primary_degradation: dKey,
            degradation_strength: dStr,
            category: '汚れ'
          }
        });
      }
      dirtComboIdx++;
    }
  }

  // 6. 紛らわしい文字: {dual_scale, non_scale_numbers, extra_labels, danger_band_numbers} x {0.5, 0.9} x 5 ranges -> 40
  const distractorKeys = ['dual_scale', 'non_scale_numbers', 'extra_labels', 'danger_band_numbers'];
  const distractorStrengths = [0.5, 0.9];
  let distComboIdx = 0;
  for (const distKey of distractorKeys) {
    for (const distStr of distractorStrengths) {
      const rangeSubset = (distComboIdx % 2 === 0) ? [0, 1, 2, 3, 4] : [5, 6, 7, 8, 9];
      for (let step = 0; step < rangeSubset.length; step++) {
        const rIdx = rangeSubset[step];
        const meterKey = RANGES_ORDER[rIdx];
        const prefix = METER_DEFS[meterKey].prefix;
        const pct = NON_ROUND_PCTS[(distComboIdx * 5 + step) % NON_ROUND_PCTS.length];
        const sLabel = String(Math.round(distStr * 100)).padStart(2, '0');
        const id = `${prefix}_v${String(pct).padStart(2, '0')}_${distKey}_s${sLabel}_紛らわしい文字`;
        const appearance = makeAppearance(210 + distComboIdx * 5 + step, distKey === 'danger_band_numbers' ? { danger_band: true } : {});
        addItem({
          meterKey,
          pct,
          cam: { yaw: 0, pitch: 0 },
          lighting: 'normal',
          id,
          subfolder: '紛らわしい文字',
          appearance,
          round2: { seed: ++seedCounter, [distKey]: distStr },
          condition: {
            meter_id: meterKey,
            value_percent: pct,
            camera_yaw: 0,
            camera_pitch: 0,
            lighting: 'normal',
            blur: 'none',
            primary_distractor: distKey,
            distractor_strength: distStr,
            category: '紛らわしい文字'
          }
        });
      }
      distComboIdx++;
    }
  }

  // 7. 背景と画質: {cluttered_background, small_in_frame, sensor_noise, jpeg_compression, partial_occlusion, partial_crop, color_cast, uneven_lighting} x {0.5, 0.9} x 3 ranges -> 48
  const bgKeys = [
    'cluttered_background',
    'small_in_frame',
    'sensor_noise',
    'jpeg_compression',
    'partial_occlusion',
    'partial_crop',
    'color_cast',
    'uneven_lighting'
  ];
  const bgStrengths = [0.5, 0.9];
  let bgComboIdx = 0;
  for (const bgKey of bgKeys) {
    for (const bgStr of bgStrengths) {
      const rangeIndices = [
        (bgComboIdx * 3 + 0) % RANGES_ORDER.length,
        (bgComboIdx * 3 + 1) % RANGES_ORDER.length,
        (bgComboIdx * 3 + 2) % RANGES_ORDER.length
      ];
      for (let step = 0; step < rangeIndices.length; step++) {
        const rIdx = rangeIndices[step];
        const meterKey = RANGES_ORDER[rIdx];
        const prefix = METER_DEFS[meterKey].prefix;
        const pct = NON_ROUND_PCTS[(bgComboIdx * 3 + step) % NON_ROUND_PCTS.length];
        const sLabel = String(Math.round(bgStr * 100)).padStart(2, '0');
        const id = `${prefix}_v${String(pct).padStart(2, '0')}_${bgKey}_s${sLabel}_背景と画質`;
        const appearance = makeAppearance(250 + bgComboIdx * 3 + step);
        addItem({
          meterKey,
          pct,
          cam: { yaw: 0, pitch: 0 },
          lighting: 'normal',
          id,
          subfolder: '背景と画質',
          appearance,
          round2: { seed: ++seedCounter, [bgKey]: bgStr },
          condition: {
            meter_id: meterKey,
            value_percent: pct,
            camera_yaw: 0,
            camera_pitch: 0,
            lighting: 'normal',
            blur: 'none',
            primary_quality_factor: bgKey,
            factor_strength: bgStr,
            category: '背景と画質'
          }
        });
      }
      bgComboIdx++;
    }
  }

  return plan;
}

module.exports = {
  METER_DEFS,
  RANGES_ORDER,
  NON_ROUND_PCTS,
  makeAppearance,
  buildFinalSetPlan,
  DISTRACTOR_KINDS,
  validateFrame
};

if (require.main === module) {
  const fs = require('node:fs');
  const path = require('node:path');
  if (process.argv[2] !== '--validate' || !process.argv[3]) throw new Error('Usage: node batch/final_set_plan.cjs --validate <dataset-dir>');
  const plan = buildFinalSetPlan();
  for (const item of plan) {
    const truth = JSON.parse(fs.readFileSync(path.join(process.argv[3], item.subfolder, `${item.id}.json`), 'utf8'));
    validateFrame(item, truth);
  }
  console.log(`PLAN VALIDATION PASSED: ${plan.length} frames; degradations, distractor kinds, strengths, seeds, appearance, camera and lighting match plan.`);
  if (process.argv.includes('--self-test')) {
    const item = plan.find(p => p.condition.primary_distractor === 'dual_scale');
    const truth = JSON.parse(fs.readFileSync(path.join(process.argv[3], item.subfolder, `${item.id}.json`), 'utf8'));
    const polluted = structuredClone(truth);
    polluted.degradations.dial_dirt = { strength: 0.9, seed: truth.seed };
    assert.throws(() => validateFrame(item, polluted), /degradations differ/);
    const mixed = structuredClone(truth);
    mixed.distractors.push({ kind: 'extra_label' });
    assert.throws(() => validateFrame(item, mixed), /distractor kinds differ/);
    const missing = structuredClone(truth);
    missing.distractors = [];
    assert.throws(() => validateFrame(item, missing), /distractor kinds differ/);
    console.log('REGRESSION SELF-CHECK PASSED: accumulated degradation, mixed distractor kinds and missing distractors are rejected.');
  }
}
