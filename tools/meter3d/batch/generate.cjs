'use strict';
// batch/generate.cjs - Headless Chrome batch generator for 3D meter synthetic dataset.
// No npm dependencies. Uses standard Node.js libraries and Chrome DevTools Protocol.

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { setTimeout: delay } = require('node:timers/promises');
const { DISTRACTOR_KINDS, validateFrame } = require('./final_set_plan.cjs');

const APPEARANCE_OPTIONS = {
  sweep_deg: ['270', '240', '300'], dial_color: ['white', 'black', 'cream'],
  number_position: ['inside', 'outside'], font: ['sans', 'serif', 'mono'],
  needle_shape: ['lance', 'arrow', 'counterweight'], needle_color: ['black', 'red'],
  bezel_color: ['black', 'silver', 'brass'], danger_band: ['false', 'true'], max_pointer: ['false', 'true']
};

const ROUND2_KEYS = [
  'dual_scale', 'non_scale_numbers', 'extra_labels', 'danger_band_numbers',
  'cluttered_background', 'dial_yellowing', 'dial_dirt', 'faded_print',
  'glass_scratches', 'glass_fog', 'glass_droplets', 'uneven_lighting',
  'color_cast', 'bezel_shadow', 'small_in_frame', 'sensor_noise',
  'jpeg_compression', 'partial_occlusion', 'partial_crop'
];

function parseArgs(argv) {
  const options = {
    out: 'C:/卒研/合成画像/set_20261021',
    meters: 'pressure-150,pressure-400,temperature-100',
    values: '7,27,48,71,93',
    cameras: '0:0,30:0,45:0,0:25',
    lightings: 'normal,glare',
    distance: 5.6,
    legacyGrid: false,
    dryRun: false,
    samples: null,
    appearances: Object.fromEntries(Object.entries(APPEARANCE_OPTIONS).map(([k,v]) => [k,v.join(',')])),
    maxPointerPercent: 85,
    seeds: '1',
    finalSet: false,
    categories: null,
    outSpecified: false,
    round2: Object.fromEntries(ROUND2_KEYS.map(k => [k, '0'])),
    chrome: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  };

  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    const keyName = arg.startsWith('--') ? arg.slice(2).replaceAll('-', '_') : '';
    if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    } else if (arg === '--final-set') {
      options.finalSet = true;
    } else if (arg === '--categories' && i + 1 < argv.length) {
      options.categories = argv[++i].split(',');
    } else if (arg === '--legacy-grid') {
      options.legacyGrid = true;
    } else if (arg === '--dry-run') {
      options.dryRun = true;
    } else if (arg === '--samples' && i + 1 < argv.length) {
      options.samples = Number(argv[++i]);
    } else if (arg === '--max-pointer-percent' && i + 1 < argv.length) {
      options.maxPointerPercent = Number(argv[++i]);
    } else if (arg === '--seed' && i + 1 < argv.length) {
      options.seeds = argv[++i];
    } else if (Object.hasOwn(APPEARANCE_OPTIONS, keyName) && i + 1 < argv.length) {
      options.appearances[keyName] = argv[++i];
    } else if (ROUND2_KEYS.includes(keyName) && i + 1 < argv.length) {
      options.round2[keyName] = argv[++i];
    } else if (arg === '--out' && i + 1 < argv.length) {
      options.out = argv[++i];
      options.outSpecified = true;
    } else if (arg === '--meters' && i + 1 < argv.length) {
      options.meters = argv[++i];
    } else if (arg === '--values' && i + 1 < argv.length) {
      options.values = argv[++i];
    } else if (arg === '--cameras' && i + 1 < argv.length) {
      options.cameras = argv[++i];
    } else if (arg === '--lightings' && i + 1 < argv.length) {
      options.lightings = argv[++i];
    } else if (arg === '--distance' && i + 1 < argv.length) {
      options.distance = Number(argv[++i]);
    } else if (arg === '--chrome' && i + 1 < argv.length) {
      options.chrome = argv[++i];
    } else {
      console.error(`Unknown argument: ${arg}`);
      printHelp();
      process.exit(1);
    }
  }
  return options;
}

function printHelp() {
  console.log(`
Usage: node batch/generate.cjs [options]

Generates synthetic 1280x960 meter images and truth JSON files in headless Chrome.

Options:
  --final-set          Generate the 7-subfolder final synthetic test set (294 frames across 7 categories)
  --categories <list>  With --final-set, regenerate only these comma-separated category folders; preserve manifest
  --out <dir>          Output directory (default: C:/卒研/合成画像/set_20261021, or テスト用_20261021 with --final-set)
  --meters <list>      Comma-separated meter keys (default: pressure-150,pressure-400,temperature-100)
  --values <list>      Comma-separated value percentages of scale (default: 7,27,48,71,93)
  --cameras <list>     Comma-separated yaw:pitch pairs (default: 0:0,30:0,45:0,0:25)
  --lightings <list>   Comma-separated lighting modes: normal,glare (default: normal,glare)
  --distance <num>     Camera distance (default: 5.6)
  --legacy-grid        Original default 120-condition grid, original IDs and type-specific looks
  --dry-run            Validate and print the plan without Chrome or writing files
  --samples <int>      Bounded cyclic sampling across meters/values/cameras/lightings (e.g. 12)
  --sweep-deg <list>   270,240,300 (appearance lists cycle by frame, not a Cartesian product)
  --dial-color <list>  white,black,cream
  --number-position <list> inside,outside
  --font <list>        sans,serif,mono (Arial, Georgia, Courier New)
  --needle-shape <list> lance,arrow,counterweight
  --needle-color <list> black,red
  --bezel-color <list> black,silver,brass
  --danger-band <list> false,true (red upper 15%)
  --max-pointer <list> false,true (separate red needle)
  --max-pointer-percent <num> Position within min..max (default: 85)
                      Appearance & Round 2 options are ignored with --legacy-grid.
  --seed <list>        Comma-separated integer seeds 0..9999 (default: 1)
  --dual-scale <list>  0..1 strengths for inner dual scale (psi / kgf/cm² / °F)
  --non-scale-numbers <list> 0..1 strengths for 1.6 / JIS B 7505 / serial / ×0.1 / A-101
  --extra-labels <list> 0..1 strengths for large unit / maker text
  --danger-band-numbers <list> 0..1 strengths for numbers on red danger band
  --cluttered-background <list> 0..1 strengths for procedural pipes/stains/parts
  --dial-yellowing <list> 0..1 strengths for dial yellowing
  --dial-dirt <list>   0..1 strengths for dirt spots & smudges
  --faded-print <list> 0..1 strengths for faded print
  --glass-scratches <list> 0..1 strengths for glass scratches
  --glass-fog <list>   0..1 strengths for glass fog/condensation
  --glass-droplets <list> 0..1 strengths for water droplets
  --uneven-lighting <list> 0..1 strengths for uneven lighting/vignetting
  --color-cast <list>  0..1 strengths for fluorescent green / warm evening cast
  --bezel-shadow <list> 0..1 strengths for bezel rim shadow
  --small-in-frame <list> 0..1 strengths for distant small meter in frame
  --sensor-noise <list> 0..1 strengths for sensor grain noise
  --jpeg-compression <list> 0..1 strengths for 8x8 JPEG block artifacts
  --partial-occlusion <list> 0..1 strengths for tag/finger occlusion at edge
  --partial-crop <list> 0..1 strengths for dial partly cropped out of frame
  --chrome <path>      Path to chrome.exe (default: C:/Program Files/Google/Chrome/Application/chrome.exe)
  --help, -h           Show this help message and exit
`);
}

const METER_DEFS = {
  'pressure-150': { meter_type: 'pressure', range: '150', max: 150, prefix: 'p150' },
  'pressure-400': { meter_type: 'pressure', range: '400', max: 400, prefix: 'p400' },
  'temperature-100': { meter_type: 'temperature', range: '100', max: 100, prefix: 't100' },
  'pressure-1.0': { meter_type: 'pressure', range: '1.0', max: 1, prefix: 'p1' },
  'pressure-1.6': { meter_type: 'pressure', range: '1.6', max: 1.6, prefix: 'p1_6' },
  'pressure-250': { meter_type: 'pressure', range: '250', max: 250, prefix: 'p250' },
  'pressure-16': { meter_type: 'pressure', range: '16', max: 16, prefix: 'p16' },
  'pressure--0.1:0.5': { meter_type: 'pressure', range: '-0.1:0.5', min: -0.1, max: 0.5, prefix: 'pneg' },
  'temperature-60': { meter_type: 'temperature', range: '60', max: 60, prefix: 't60' },
  'temperature--20:120': { meter_type: 'temperature', range: '-20:120', min: -20, max: 120, prefix: 'tneg' }
};

function getLightingParams(mode, yaw, pitch) {
  if (mode === 'glare') {
    let az, el;
    if (yaw === 0 && pitch === 0) {
      az = 15;
      el = 8;
    } else if (yaw === 30 && pitch === 0) {
      az = -20;
      el = 8;
    } else if (yaw === 45 && pitch === 0) {
      az = -36;
      el = 7;
    } else if (yaw === 0 && pitch === 25) {
      az = 0;
      el = 0;
    } else {
      // General reflection targeting point (0.55, 0.3) on dome
      az = Math.round(yaw > 0 ? -0.8 * yaw : 15);
      el = Math.max(0, Math.min(85, Math.round(pitch === 0 ? 8 : 0)));
    }
    return {
      light_azimuth_deg: az,
      light_elevation_deg: el,
      light_intensity: 2.4,
      glass_reflection: 0.9
    };
  } else if (mode === 'normal') {
    // Normal diffuse illumination
    return {
      light_azimuth_deg: -35,
      light_elevation_deg: 45,
      light_intensity: 1.2,
      glass_reflection: 0.2
    };
  } else {
    throw new Error(`Invalid lighting mode: ${mode}. Must be 'normal' or 'glare'.`);
  }
}

async function main() {
  const options = parseArgs(process.argv);
  if (!Number.isFinite(options.distance) || options.distance < 4.8 || options.distance > 9) throw new Error('distance must be 4.8..9');
  if (options.samples !== null && (!Number.isSafeInteger(options.samples) || options.samples < 1)) throw new Error('samples must be a positive integer');
  if (!Number.isFinite(options.maxPointerPercent) || options.maxPointerPercent < 0 || options.maxPointerPercent > 100) throw new Error('max-pointer-percent must be 0..100');
  const appearanceLists = Object.fromEntries(Object.entries(options.appearances).map(([key,list]) => {
    const values = list.split(',').map(v=>v.trim());
    if (values.some(v=>!APPEARANCE_OPTIONS[key].includes(v))) throw new Error(`Invalid ${key}: ${list}`);
    return [key,values];
  }));
  const seedList = options.seeds.split(',').map(s => {
    const n = Number(s.trim());
    if (!Number.isSafeInteger(n) || n < 0 || n > 9999) throw new Error(`Invalid seed '${s}' (must be integer 0..9999)`);
    return n;
  });
  if (seedList.length === 0) throw new Error('At least one seed must be specified.');
  const round2Lists = Object.fromEntries(Object.entries(options.round2).map(([key, list]) => {
    const values = list.split(',').map(s => {
      const n = Number(s.trim());
      if (s.trim() === '' || !Number.isFinite(n) || n < 0 || n > 1) throw new Error(`Invalid ${key} strength '${s}' (must be 0..1)`);
      return n;
    });
    if (values.length === 0) throw new Error(`At least one value required for ${key}`);
    return [key, values];
  }));
  if (options.finalSet && !options.outSpecified) {
    options.out = 'C:/卒研/合成画像/テスト用_20261021';
  }
  const outDir = path.resolve(options.out);

  const root = path.resolve(__dirname, '..');
  const htmlPath = path.join(root, 'meter3d.html');
  const html = fs.readFileSync(htmlPath, 'utf8');

  let plan = [];
  let meterKeys = [];
  let valuePcts = [];
  let cameras = [];
  let lightings = [];

  if (options.finalSet) {
    const { buildFinalSetPlan } = require('./final_set_plan.cjs');
    plan = buildFinalSetPlan();
  } else {
    // 1. Strict input grid validation
    meterKeys = options.meters.split(',').map(s => s.trim()).filter(Boolean);
    if (meterKeys.length === 0) throw new Error('At least one meter must be specified.');
    for (const k of meterKeys) {
      if (!METER_DEFS[k]) throw new Error(`Unknown meter definition: '${k}'. Allowed: ${Object.keys(METER_DEFS).join(', ')}`);
    }

    valuePcts = options.values.split(',').map(s => {
      const n = Number(s.trim());
      if (!Number.isFinite(n) || n < 0 || n > 100) {
        throw new Error(`Invalid percentage value: '${s}'. Must be a number between 0 and 100.`);
      }
      return n;
    });
    if (valuePcts.length === 0) throw new Error('At least one value percentage must be specified.');

    cameras = options.cameras.split(',').map(s => {
      const parts = s.trim().split(':');
      if (parts.length !== 2) throw new Error(`Invalid camera format: '${s}'. Expected 'yaw:pitch'.`);
      const y = Number(parts[0]);
      const p = Number(parts[1]);
      if (!Number.isFinite(y) || y < -60 || y > 60) throw new Error(`Invalid yaw '${parts[0]}' in '${s}' (range: -60 to 60).`);
      if (!Number.isFinite(p) || p < -60 || p > 60) throw new Error(`Invalid pitch '${parts[1]}' in '${s}' (range: -60 to 60).`);
      return { yaw: y, pitch: p };
    });
    if (cameras.length === 0) throw new Error('At least one camera pose must be specified.');

    lightings = options.lightings.split(',').map(s => {
      const l = s.trim();
      if (l !== 'normal' && l !== 'glare') {
        throw new Error(`Invalid lighting: '${l}'. Allowed values are 'normal' or 'glare'.`);
      }
      return l;
    });
    if (lightings.length === 0) throw new Error('At least one lighting mode must be specified.');

    // Validate unique IDs upfront before launching Chrome
    const plannedIds = new Set();
    for (const m of meterKeys) {
      for (const v of valuePcts) {
        for (const c of cameras) {
          for (const l of lightings) {
            plan.push({meterKey:m,pct:v,cam:c,lighting:l});
          }
        }
      }
    }

    if (options.samples !== null) {
      plan = Array.from({length:options.samples}, (_,i)=>({meterKey:meterKeys[i%meterKeys.length],pct:valuePcts[i%valuePcts.length],cam:cameras[i%cameras.length],lighting:lightings[i%lightings.length]}));
    }
    plan = plan.map((item,index)=>{
      const {meterKey,pct,cam,lighting}=item;
      const id = `${METER_DEFS[meterKey].prefix}_v${pct}_y${cam.yaw}p${cam.pitch}_${lighting}${options.legacyGrid?'':`_a${String(index+1).padStart(3,'0')}`}`;
      if (plannedIds.has(id)) throw new Error(`Duplicate frame ID detected in grid plan: ${id}`);
      plannedIds.add(id);
      const appearance = options.legacyGrid ? {} : Object.fromEntries(Object.entries(appearanceLists).map(([key,values])=>{
        const value=values[index%values.length];
        return [key,key==='sweep_deg'?Number(value):['danger_band','max_pointer'].includes(key)?value==='true':value];
      }));
      const round2 = options.legacyGrid ? {} : {
        seed: seedList[index % seedList.length],
        ...Object.fromEntries(Object.entries(round2Lists).map(([key, values]) => [key, values[index % values.length]]))
      };
      return {...item,id,appearance,round2};
    });
  }
  if (options.categories) {
    if (!options.finalSet) throw new Error('--categories requires --final-set');
    const known = new Set(plan.map(item => item.subfolder));
    for (const cat of options.categories) if (!known.has(cat)) throw new Error(`Unknown category: ${cat}`);
    plan = plan.filter(item => options.categories.includes(item.subfolder));
  }
  const totalFrames = plan.length;
  console.log(`Grid plan validated: ${totalFrames} frames (${options.samples===null?'grid':'bounded cyclic sample'}, ${options.legacyGrid?'legacy conditions':'cycling appearances'})`);
  console.log(`Target directory: ${outDir}`);
  if (options.dryRun) {
    console.log(JSON.stringify(plan, null, 2));
    return;
  }
  fs.mkdirSync(outDir, { recursive: true });

  let server, chrome, socket, profile;
  let nextId = 0;
  const pending = new Map();
  const errors = [];

  function command(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`CDP command timeout: ${method}`));
      }, 30000);
      pending.set(id, { resolve, reject, timeout });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) {
      throw new Error(`Browser evaluate error: ${JSON.stringify(result.exceptionDetails)}`);
    }
    return result.result.value;
  }

  const startTime = Date.now();
  const frameManifest = [];

  try {
    // 2. Start HTTP server serving meter3d.html
    server = http.createServer((req, res) => {
      if (req.url !== '/' && req.url !== '/meter3d.html') {
        res.writeHead(404).end();
        return;
      }
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.end(html);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const serverPort = server.address().port;

    // 3. Launch headless Chrome with WebGL
    const checkDir = path.join(root, '.checks');
    fs.mkdirSync(checkDir, { recursive: true });
    profile = fs.mkdtempSync(path.join(checkDir, 'chrome-batch-'));

    chrome = spawn(options.chrome, [
      '--headless=new', '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
      '--disable-background-networking', '--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
      '--user-data-dir=' + profile, '--disk-cache-dir=' + path.join(checkDir, 'chrome-cache'),
      '--window-size=1280,960', 'about:blank'
    ], { stdio: 'ignore', windowsHide: true });
    chrome.on('error', error => errors.push(error.message));

    const portFile = path.join(profile, 'DevToolsActivePort');
    let cdpPort;
    for (let i = 0; i < 150; i++) {
      if (fs.existsSync(portFile)) {
        cdpPort = fs.readFileSync(portFile, 'utf8').split('\n')[0];
        break;
      }
      await delay(100);
    }
    if (!cdpPort) throw new Error('Chrome did not open its DevTools debugging port');

    const pages = await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json();
    const targetPage = pages.find(p => p.type === 'page');
    if (!targetPage) throw new Error('No page target found in Chrome');

    socket = new WebSocket(targetPage.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });

    socket.onmessage = message => {
      const response = JSON.parse(message.data);
      if (response.id) {
        const task = pending.get(response.id);
        if (!task) return;
        pending.delete(response.id);
        clearTimeout(task.timeout);
        response.error ? task.reject(new Error(JSON.stringify(response.error))) : task.resolve(response.result);
      } else if (response.method === 'Runtime.exceptionThrown') {
        errors.push(JSON.stringify(response.params.exceptionDetails));
      } else if (response.method === 'Runtime.consoleAPICalled' && response.params.type === 'error') {
        errors.push(response.params.args.map(a => a.description || a.value).join(' '));
      }
    };

    await command('Runtime.enable');
    await command('Page.enable');
    await command('Page.navigate', { url: `http://127.0.0.1:${serverPort}/meter3d.html` });

    // Wait until window.meter3dApi is initialized
    let apiReady = false;
    for (let attempt = 0; attempt < 200; attempt++) {
      const check = await evaluate("typeof window.meter3dApi !== 'undefined' && typeof window.meter3dApi.setParams === 'function'");
      if (check) { apiReady = true; break; }
      await delay(100);
    }
    if (!apiReady) throw new Error('meter3dApi failed to initialize in page');

    console.log('Headless Chrome and 3D WebGL engine initialized.');

    // 4. Execution loop across all combinations
    let frameIndex = 0;
    for (const item of plan) {
      const {meterKey,pct,cam,lighting,id,appearance,round2,subfolder,lightingParams,targetBlurWidth} = item;
      const meterDef = METER_DEFS[meterKey];
      const minValue = meterDef.min || 0;
      const trueValue = Number((minValue + (pct / 100) * (meterDef.max-minValue)).toFixed(8));
      frameIndex++;
      const frameStart = Date.now();
      const activeLighting = lightingParams || getLightingParams(lighting, cam.yaw, cam.pitch);

      const appliedParams = {
        // setParams merges into the previous frame: send every mutable setting each time.
        ...Object.fromEntries(Object.entries(APPEARANCE_OPTIONS).map(([k, values]) => [k, k === 'sweep_deg' ? Number(values[0]) : ['danger_band', 'max_pointer'].includes(k) ? false : values[0]])),
        ...(meterDef.meter_type === 'temperature' ? { dial_color: 'cream', needle_color: 'red', needle_shape: 'lance', bezel_color: 'silver' } : { needle_shape: 'counterweight' }),
        seed: 1,
        ...Object.fromEntries(ROUND2_KEYS.map(k => [k, 0])),
        meter_type: meterDef.meter_type,
        range: meterDef.range,
        value: trueValue,
        yaw_deg: cam.yaw,
        pitch_deg: cam.pitch,
        distance: options.distance,
        ...appearance,
        max_pointer_value: Number((minValue + (options.maxPointerPercent/100)*(meterDef.max-minValue)).toFixed(8)),
        ...activeLighting,
        ...round2
      };

      const condition = item.condition ? { ...item.condition } : {
        meter_id: meterKey,
        value_percent: pct,
        camera_yaw: cam.yaw,
        camera_pitch: cam.pitch,
        lighting: lighting,
        blur: 'none'
      };
      if (targetBlurWidth) {
        condition.target_blur_width = targetBlurWidth;
      }

      // Atomically update parameters and export 1280x960 frame in page
      const exportExpr = `(() => {
        window.meter3dApi.setParams(${JSON.stringify(appliedParams)});
        return window.meter3dApi.exportFrame();
      })()`;
      const frameResult = await evaluate(exportExpr);

      if (!frameResult || !frameResult.png_data_url || !frameResult.truth) {
        throw new Error(`Export returned empty frame for id=${id}`);
      }

      // The demo exports distractor strengths in degradations too; keep the dataset fields separate.
      if (options.finalSet) validateFrame(item, frameResult.truth, true, options.distance);
      frameResult.truth.degradations = Object.fromEntries(Object.entries(frameResult.truth.degradations)
        .filter(([k]) => !Object.hasOwn(DISTRACTOR_KINDS, k)));
      if (options.finalSet) validateFrame(item, frameResult.truth, false, options.distance);

      const pngBuffer = Buffer.from(frameResult.png_data_url.split(',')[1], 'base64');
      const targetDir = subfolder ? path.join(outDir, subfolder) : outDir;
      fs.mkdirSync(targetDir, { recursive: true });

      const pngPath = path.join(targetDir, `${id}.png`);
      fs.writeFileSync(pngPath, pngBuffer);

      const recordJson = {
        id,
        category: subfolder || 'general',
        ...frameResult.truth,
        condition,
        applied_params: appliedParams
      };
      const jsonPath = path.join(targetDir, `${id}.json`);
      fs.writeFileSync(jsonPath, JSON.stringify(recordJson, null, 2));

      const elapsedSec = ((Date.now() - frameStart) / 1000).toFixed(2);
      frameManifest.push({
        id,
        category: subfolder || 'general',
        file: subfolder ? `${subfolder}/${id}.png` : `${id}.png`,
        json: subfolder ? `${subfolder}/${id}.json` : `${id}.json`,
        true_value: trueValue,
        min_value: minValue,
        max_value: meterDef.max,
        condition,
        appearance: frameResult.truth.appearance,
        seed: frameResult.truth.seed,
        degradations: frameResult.truth.degradations,
        distractor_count: frameResult.truth.distractors.length
      });

            if (frameIndex % 10 === 0 || frameIndex === totalFrames) {
              console.log(`[${frameIndex}/${totalFrames}] ${id} (${elapsedSec}s)`);
            }
    }

    const totalSeconds = ((Date.now() - startTime) / 1000).toFixed(2);
    const manifest = {
      generated_at: new Date().toISOString(),
      total_frames: frameManifest.length,
      elapsed_seconds: Number(totalSeconds),
      final_set: options.finalSet,
      grid: options.finalSet ? {
        mode: 'final_synthetic_test_set_20261021',
        total_frames: totalFrames,
        categories: {
          '正面': 60,
          '斜め': 50,
          '反射': 30,
          'ブレ': 30,
          '汚れ': 36,
          '紛らわしい文字': 40,
          '背景と画質': 48
        }
      } : {
        meters: meterKeys,
        value_percentages: valuePcts,
        cameras,
        lightings,
        camera_distance: options.distance,
        legacy_grid: options.legacyGrid, samples: options.samples,
        appearances: options.legacyGrid ? {} : appearanceLists, max_pointer_percent: options.maxPointerPercent,
        seeds: options.legacyGrid ? [] : seedList,
        round2: options.legacyGrid ? {} : round2Lists
      },
      frames: frameManifest
    };
    if (!options.categories) fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

    console.log(`SUCCESS: Generated ${frameManifest.length} frames in ${totalSeconds}s.`);
    console.log(options.categories ? 'Partial regeneration: existing manifest preserved; per-frame JSON is authoritative.' : `Manifest written to: ${path.join(outDir, 'manifest.json')}`);

    if (errors.length > 0) {
      console.warn('Browser recorded non-fatal errors during run:', errors);
    }
  } finally {
    if (socket && socket.readyState === WebSocket.OPEN) {
      try { await command('Browser.close'); } catch {}
      socket.close();
    }
    if (chrome && chrome.exitCode === null) {
      await Promise.race([new Promise(resolve => chrome.once('exit', resolve)), delay(3000)]);
      if (chrome.exitCode === null) chrome.kill();
    }
    if (server) {
      server.close();
    }
    if (profile) {
      await delay(300);
      if (!path.resolve(profile).startsWith(path.join(root, '.checks') + path.sep)) throw new Error('Refusing cleanup outside workspace .checks');
      try {
        fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      } catch {}
    }
  }
}

main().catch(err => {
  console.error('Fatal batch generation error:', err);
  process.exit(1);
});
