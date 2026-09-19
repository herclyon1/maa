/* lens-webgl.js — the lifted segment lens as a WebGL2 overlay (README §0.8.6 the chain, §0.8.7 the wiring). One line to include:
     <script src="assets/lens/lens-webgl.js"></script>
   then
     const lens = LensWebGL.create(canvas, { sets, backdrop, dpr });         // once: the canvas overlays the control's region (position absolute, pointer-events none)
     lens.setState({ cx, cy, w, h, lift, wh });                               // every tick: uniforms only (cx, cy = the lens centre in CANVAS pt; w × h = the model size → the
                                                                              //   nearest set; lift = the glass progress 0 … 1; wh = W/H of the capture box, view.js's abFrame rule)
     lens.redrawBackdrop();                                                   // when what lies under the lens changed (a render, a value flip)
   The canvas paints ONLY the capsule (the displaced copies, the label copy, the fringe, the highlight, the inner shadow) and, outside it, the
   glassBackground ring shadow + KeyFill dark line as a black overlay (they darken the page multiplicatively) — everything else stays
   transparent, the live DOM shows through. What the taps read beyond the capsule (the wrapper's 16-pt margin) comes from the backdrop
   textures the page draws (`backdrop(ctx, which)`: "page" = what lies under the lens without the segment labels, "labels" = the labels
   alone, both in canvas pt; drawn at init and at redrawBackdrop()).
   sets: { "<w>": { bg, lab, ab, S, Sab, h } } — the map files of a width (the same files the SVG filters reference), S = data-s of the bg / lab
   filters, Sab = data-s of the fringe filter, h = the set's height; LensWebGL.setsFromFilters("seg") reads them off the inline <svg>.
   Chain and constants: lens-webgl-test.html's shaders, verbatim (their sources in the comments): pass 1 = the backdrop copy through the bg map
   with the DestOut punch, the ring shadow (keyfill §4), the built-in KeyFill dark line (keyfill §5.1), the label copy through the lab map
   clipped to the capsule, the inner shadow (keyfill §5.2c, precomputed per set); pass 2 = the 7-tap dispersion (formula §3b) over pass 1,
   the #36 highlight through the vibrant matrix (keyfill §2), the outside overlay. Maps sampled bilinearly, no engine correction (§0.8.6). */
(function () {
  const VS = `#version 300 es
in vec2 a; out vec2 v; uniform vec4 u_quad; uniform vec2 u_origin; uniform vec2 u_view;
void main(){ v = u_quad.xy + a * u_quad.zw; vec2 c = (v - u_origin) / u_view * 2.0 - 1.0; gl_Position = vec4(c.x, -c.y, 0.0, 1.0); }`;
  const COMMON = `
precision highp float;
float sdf(vec2 p, vec2 half_, float r){ vec2 q = abs(p) - (half_ - vec2(r)); return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
vec2 nrm(vec2 p, vec2 half_, float r){ vec2 q = abs(p) - (half_ - vec2(r)); vec2 g = (max(q.x, q.y) > 0.0) ? max(q, 0.0) : ((q.x > q.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0)); return normalize(g) * sign(p + vec2(1e-6)); }
float erf_(float x){ float s = sign(x); x = abs(x); float t = 1.0 / (1.0 + 0.3275911 * x); float y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * exp(-x * x); return s * y; }
float N(float x){ return 0.5 * (1.0 + erf_(x / 1.41421356)); }
float sat(float x){ return clamp(x, 0.0, 1.0); }
vec2 decode(vec2 rg, float S){ return (rg - 128.0 / 255.0) * S; }
/* glassBackground ring shadow (keyfill §4; keys offset 8 / opacity .1 / stroke 4 / blur 3 / mask 0): black α = .1·[N((d_r + 4)/3) − N(d_r/3)], d_r = the SDF of the capsule shifted 8 pt down; drawn inside and outside */
float ringTerm(vec2 pl, vec2 half_, float r){ float dr = sdf(pl - vec2(0.0, 8.0), half_, r); return sat(N((dr + 4.0) / 3.0) - N(dr / 3.0)) * 0.1; }
/* glassBackground built-in KeyFill = the outer 1 pt dark line (keyfill §5.1; keys Amount .5 → uniform 1/.5 − 2 = 0 (B6-3), ColorBias −.3, EffectOffset −.6667, Height 1, Angle π/2 → dir (sin θ, −cos θ) = (1, 0), SpreadSDR 2.0944 → S = cos = −.5;
   e = −(d + offset), prof = mix(1, 1 − e, .75), aa = sat((d + off + h)/fw + .5)·sat(e/fw + .5) with fw = fwidth (keyfill §2 B6-2), k = v·ang_key + v·ang_fill) → returns k */
float darkLineK(float d, vec2 n){ float off = -0.6667, h = 1.0; float e = -(d + off); float fw = max(fwidth(e), 1e-4);
  if (!(d + off < fw * 0.5 && e < h + fw * 0.5)) return 0.0;
  float prof = mix((1.0 - e / h) != 0.0 ? 1.0 : 0.0, 1.0 - sat(e / h), 0.75);
  float aa = sat((d + off + h) / fw + 0.5) * sat(e / fw + 0.5); float vv = prof * aa; float S_ = -0.5; vec2 dir = vec2(1.0, 0.0);
  return vv * sat((dot(n, dir) - S_) / (1.0 - S_)) + vv * sat((dot(-n, dir) - S_) / (1.0 - S_)); }
`;
  const FS1 = `#version 300 es
${COMMON}
in vec2 v; out vec4 o;
uniform sampler2D t_page, t_lab, m_bg, m_lab, t_ish; uniform vec2 u_page; uniform vec4 u_lens; uniform float u_S; uniform float u_p;
vec4 page(vec2 p){ return texture(t_page, p / u_page); }
vec4 lab(vec2 p){ return texture(t_lab, p / u_page); }
vec4 over(vec4 s, vec4 d){ return s + d * (1.0 - s.a); }
void main(){
  vec2 C = u_lens.xy + u_lens.zw * 0.5, half_ = u_lens.zw * 0.5; float r = min(22.0, half_.y);   /* the segment lens: r 22 clamped to h/2 (DestOut cornerRadius stays 22 through the drag) */
  vec2 pl = v - C; float d = sdf(pl, half_, r); vec2 n = nrm(pl, half_, r); float fwd = max(fwidth(d), 1e-4);
  float M = sat(0.5 - d / fwd);
  vec4 under = over(lab(v), page(v));
  vec2 uv = (v - u_lens.xy) / u_lens.zw; bool inBox = uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0;
  vec4 mb = inBox ? texture(m_bg, uv) : vec4(128.0 / 255.0, 128.0 / 255.0, 0.0, 1.0);
  vec2 ub = decode(mb.rg, u_S) * u_p; float covb = mb.b;
  vec2 qb = v + ub; float dq = sdf(qb - C, half_, r); float Mq = sat(0.5 - dq / max(fwidth(dq), 1e-4));
  vec4 bgc = over(lab(qb) * (1.0 - Mq), page(qb));               /* layer 1 + DestOut #43: the labels only outside the capsule at the source (formula §4b) */
  vec4 col = mix(under, bgc, covb);
  col.rgb *= (1.0 - ringTerm(pl, half_, r) * u_p);               /* the ring shadow on the layer (inside; the outside part is the overlay of pass 2) */
  float k = darkLineK(d, n) * u_p; col.rgb = col.rgb * (1.0 + (-0.3) * k * (3.0 - 2.0 * col.rgb));   /* the dark line: rgb' = rgb·(1 + colorBias·k·(3 − 2·rgb)) */
  vec4 ml = inBox ? texture(m_lab, uv) : vec4(128.0 / 255.0, 128.0 / 255.0, 0.0, 1.0);
  vec2 ul = decode(ml.rg, u_S) * u_p; vec4 lc = lab(v + ul) * M; col = over(lc, col);   /* layers 2 + 4: the label copy, capsule-clipped at the destination (ClearGlass masksToBounds r 22) */
  float ish = inBox ? texture(t_ish, vec2(uv.x, 1.0 - uv.y)).r : 0.0; col.rgb *= (1.0 - ish * u_p);   /* inner shadow #21 (keyfill §5.2c); t_ish is an FBO (row 0 = bottom) */
  o = vec4(col.rgb, 1.0);
}`;
  const FS_ISH = `#version 300 es
${COMMON}
in vec2 v; out vec4 o; uniform vec4 u_lens;
float Mh(vec2 p, vec2 half_, float r){ return sdf(p, half_, r) <= 0.0 ? 1.0 : 0.0; }
void main(){ vec2 C = u_lens.xy + u_lens.zw * 0.5, half_ = u_lens.zw * 0.5; float r = min(22.0, half_.y); vec2 p = v - C;
  float sig = 3.0, off = 7.0, op = 0.06; float acc = 0.0, wsum = 0.0;   /* keyfill §5.2c: op · M · blur_σ(M − M↓off), σ = shadowRadius 3, offset (0, 7), shadowOpacity .06 */
  for (int i = -9; i <= 9; i++) for (int j = -9; j <= 9; j++) { vec2 k = vec2(float(i), float(j)); float w = exp(-dot(k, k) / (2.0 * sig * sig)); wsum += w; vec2 q = p + k; acc += w * Mh(q, half_, r) * (1.0 - Mh(q - vec2(0.0, off), half_, r)); }
  float d = sdf(p, half_, r); float M = sat(0.5 - d / max(fwidth(d), 1e-4));
  o = vec4(op * M * acc / wsum, 0.0, 0.0, 1.0); }`;
  const FS2 = `#version 300 es
${COMMON}
in vec2 v; out vec4 o;
uniform sampler2D t_a, m_ab, t_page, t_lab; uniform vec2 u_page; uniform vec4 u_lens; uniform vec4 u_wrap; uniform float u_Sab; uniform float u_wh; uniform float u_p; uniform float u_dbg;
vec4 A(vec2 p){ vec2 t = (p - u_wrap.xy) / u_wrap.zw; return texture(t_a, vec2(t.x, 1.0 - t.y)); }   /* an FBO's row 0 is the viewport's bottom: page-down y → flipped t */
vec4 over(vec4 s, vec4 d){ return s + d * (1.0 - s.a); }
vec3 V(vec3 b){ return min(vec3(1.0), 0.9118 * b + 0.1471); }   /* vibrantColorMatrix on the layer's α (keyfill §2) */
float band(float e, float h, float cosS, float bias, float curv, vec2 n, vec2 dir, float fw){
  float t = sat(e / h); float prof = mix(t < 1.0 ? 1.0 : 0.0, 1.0 - t, curv); float aa = sat(e / fw + 0.5) * sat((h - e) / fw + 0.5);
  float ang = sat((dot(n, dir) - cosS) / (1.0 - cosS)); float vv = (e < -5.0) ? 0.0 : prof * aa * ang; return vv / (1.0 + bias * (1.0 - vv)); }
void main(){
  vec2 C = u_lens.xy + u_lens.zw * 0.5, half_ = u_lens.zw * 0.5; float r = min(22.0, half_.y);
  vec2 pl = v - C; float d = sdf(pl, half_, r); vec2 n = nrm(pl, half_, r); float fw = max(fwidth(d), 1e-4); float M = sat(0.5 - d / fw);
  vec4 below = A(v);
  vec2 wuv = (v - u_wrap.xy) / u_wrap.zw; vec4 ma = texture(m_ab, wuv);
  vec2 D = decode(ma.rg, u_Sab) * vec2(u_wh, 1.0 / u_wh) * u_p; float e = ma.b * ma.a * u_p; float edr = 1.0;   /* formula §3b.3 / 3b.5: Δ × (W/H, H/W), e = the envelope × cov */
  vec3 sum = vec3(0.0);
  float ks[7] = float[7](1.0, 2.0 / 3.0, 1.0 / 3.0, 0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0); float sg[7] = float[7](1.0, 1.0, 1.0, -1.0, -1.0, -1.0, -1.0);
  for (int i = 0; i < 7; i++) { vec3 s = A(v + sg[i] * ks[i] * D).rgb; float wr = sg[i] > 0.0 ? ks[i] / 2.0 : 0.0, wg = (1.0 - ks[i]) / 3.0, wb = sg[i] < 0.0 ? ks[i] / 2.0 : 0.0; sum += vec3(wr * s.r, wg * s.g, wb * s.b); }
  vec3 col = e * edr * sum + (1.0 - e) * below.rgb;              /* §3b.7: screen = e·edr·(R/2, G/3, B/2) + (1 − e)·below */
  if (u_dbg > 0.5) { o = vec4(below.rgb, 1.0); return; }          /* instrument: pass 1 alone (?glpass=1 on the test page) */
  float eh = -d; vec2 dirK = vec2(0.0, -1.0), dirF = vec2(0.0, 1.0);   /* #36 KeyFill highlight (keyfill §2): main h 1 / cos 1.3963 / bias 0 / curvature .75; diffuse h 8 / cos(.65·1.3963) / bias 1/(.15·.5) − 2 / linear; three emits through V */
  float a1 = (band(eh, 1.0, cos(1.3963), 0.0, 0.75, n, dirK, fw) + band(eh, 1.0, cos(1.3963), 0.0, 0.75, n, dirF, fw)) * u_p;
  float a2 = band(eh, 8.0, cos(0.65 * 1.3963), 11.3333, 1.0, n, dirK, fw) * u_p; float a3 = band(eh, 8.0, cos(0.65 * 1.3963), 11.3333, 1.0, n, dirF, fw) * u_p;
  col = mix(col, V(col), sat(a1)); col = mix(col, V(col), sat(a2)); col = mix(col, V(col), sat(a3));
  /* the overlay outside the capsule: the ring shadow darkens whatever is under (black, α = ring — exact for any colour); the dark line's factor depends on the
     colour under it (rgb·(1 + colorBias·k·(3 − 2·rgb)), keyfill §5.1), so on its 1-pt row the overlay paints the page copy itself, darkened, opaque */
  float ring = ringTerm(pl, half_, r) * u_p; float k = darkLineK(d, n) * u_p;
  vec4 und = over(texture(t_lab, v / u_page), texture(t_page, v / u_page));
  vec3 lined = und.rgb * (1.0 + (-0.3) * k * (3.0 - 2.0 * und.rgb)) * (1.0 - ring);
  vec4 outside = (k > 0.0) ? vec4(lined, 1.0) : vec4(0.0, 0.0, 0.0, ring);
  o = mix(outside, vec4(col, 1.0), M);
}`;
  const loadImg = (src) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("lens-webgl: " + src)); i.src = src; });
  const create = (canvas, opts) => {
    const gl = canvas.getContext("webgl2", { antialias: false, premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: !!opts.preserve });
    if (!gl) return null;
    const DPR = opts.dpr || window.devicePixelRatio || 1, AM = opts.margin || 16;
    const W = opts.width || canvas.clientWidth || parseFloat(canvas.style.width) || canvas.width, H = opts.height || canvas.clientHeight || parseFloat(canvas.style.height) || canvas.height;   /* the canvas in pt */
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const prog = (vs, fs) => { const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p; };
    const P1 = prog(VS, FS1), PISH = prog(VS, FS_ISH), P2 = prog(VS, FS2);
    const quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    const useProg = (p) => { gl.useProgram(p); const a = gl.getAttribLocation(p, "a"); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0); };
    const U = (p, name) => gl.getUniformLocation(p, name);
    const tex = (src, premul) => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, !!premul); gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src); for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v); return t; };
    const fbo = (w, h) => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null); for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
      const f = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, f); gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0); gl.bindFramebuffer(gl.FRAMEBUFFER, null); return { t, f, w, h }; };
    const bind = (p, name, unit, t) => { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t); gl.uniform1i(U(p, name), unit); };
    /* the backdrop textures: the page draws them (canvas pt) */
    let tPage = null, tLab = null;
    /* the labels texture is NOT drawn on a transparent canvas: on macOS WebKit text over a transparent backdrop gets no font smoothing (thinner
       stems than the same text on the page — measured: the glyph's ink box 108.5–131.33 vs the page's 107.67–132). The page draws the labels OVER
       the page copy (opaque, smoothed like the DOM text), and the labels' alpha is recovered per pixel from the two opaque images:
       P = Pg·(1 − a) + ink·a → a = (P − Pg)/(ink − Pg) (opts.ink = the label colour; the channel with the largest |ink − Pg| decides) */
    /* the scratch canvases are attached to the document (off-screen) while drawn: macOS WebKit smooths text on an attached canvas like the DOM's text
       and not on a detached one (measured: the same 13 px glyph's ink box 107.67–132 attached / DOM vs 108.5–131.33 detached); iOS renders both alike */
    const scratch = document.createElement("div"); scratch.style.cssText = "position:absolute;left:-100000px;top:0;width:1px;height:1px;overflow:hidden;pointer-events:none"; document.body.appendChild(scratch);
    const draw2d = (which) => { const c = document.createElement("canvas"); c.width = canvas.width; c.height = canvas.height; c.style.cssText = `width:${W}px;height:${H}px`; scratch.appendChild(c); const x = c.getContext("2d"); x.scale(DPR, DPR); opts.backdrop(x, "page", { width: W, height: H }); if (which === "labels") opts.backdrop(x, "labels", { width: W, height: H }); return c; };
    const labelsAlpha = (cPg, cP) => { const w = cPg.width, h = cPg.height; const a = cPg.getContext("2d").getImageData(0, 0, w, h).data, b = cP.getContext("2d").getImageData(0, 0, w, h).data; const ink = opts.ink || [0, 0, 0];
      const out = new ImageData(w, h); const o = out.data;
      for (let i = 0; i < a.length; i += 4) { let best = 0, al = 0; for (let c = 0; c < 3; c++) { const den = ink[c] - a[i + c]; if (Math.abs(den) > Math.abs(best)) { best = den; al = (b[i + c] - a[i + c]) / den; } }
        al = Math.max(0, Math.min(1, al)); o[i] = ink[0] * al; o[i + 1] = ink[1] * al; o[i + 2] = ink[2] * al; o[i + 3] = al * 255; }   /* premultiplied ink·a, a */
      const c = document.createElement("canvas"); c.width = w; c.height = h; c.getContext("2d").putImageData(out, 0, 0); return c; };
    let composite = null;   /* the page + labels canvas of the last redraw (lens.backdropCanvas(): the test page paints its visible base from it, so base and copy are the same pixels) */
    const redrawBackdrop = () => { if (tPage) { gl.deleteTexture(tPage); gl.deleteTexture(tLab); } const cPg = draw2d("page"), cP = draw2d("labels"); tPage = tex(cPg, true); tLab = tex(labelsAlpha(cPg, cP), true); composite = cP; scratch.innerHTML = ""; };
    redrawBackdrop();
    /* the sets: maps per width, textures loaded on first use; the inner shadow per set */
    const sets = {}; const widths = Object.keys(opts.sets).map(Number).sort((a, b) => a - b);
    const nearest = (w) => { let best = widths[0], dd = Infinity; for (const x of widths) { const d = Math.abs(x - w); if (d < dd) { dd = d; best = x; } } return best; };
    const ISH_PX = 3;
    const loadSet = (w) => { if (sets[w]) return sets[w].ready; const s = opts.sets[w]; const st = sets[w] = { S: s.S || 40, Sab: s.Sab || 12, h: s.h, bg: null, lab: null, ab: null, ish: null, ready: null };
      st.ready = Promise.all([loadImg(s.bg), loadImg(s.lab), loadImg(s.ab)]).then(([a, b, c]) => { st.bg = tex(a); st.lab = tex(b); st.ab = tex(c); if (!st.h) st.h = a.height / (a.width / w);   /* the bg map covers the lens box: h = its height at the map's px/pt */
        st.ish = fbo(Math.round(w * ISH_PX), Math.round(st.h * ISH_PX)); gl.bindFramebuffer(gl.FRAMEBUFFER, st.ish.f); gl.viewport(0, 0, st.ish.w, st.ish.h); useProg(PISH);
        gl.uniform4f(U(PISH, "u_lens"), 0, 0, w, st.h); gl.uniform4f(U(PISH, "u_quad"), 0, 0, w, st.h); gl.uniform2f(U(PISH, "u_origin"), 0, 0); gl.uniform2f(U(PISH, "u_view"), w, st.h); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.bindFramebuffer(gl.FRAMEBUFFER, null); st.loaded = true; });
      return st.ready; };
    const loadedNearest = (w) => { const cands = widths.filter((x) => sets[x] && sets[x].loaded); if (!cands.length) return null; let best = cands[0], dd = Infinity; for (const x of cands) { const d = Math.abs(x - w); if (d < dd) { dd = d; best = x; } } return best; };
    const preload = opts.preload || [widths.includes(220) ? 220 : widths[0]]; for (const w of preload) loadSet(w);
    let A = null, last = null, stats = { gpuMs: 0, frames: 0, set: 0 };
    const clear = () => { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, canvas.width, canvas.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); };
    const setState = (s) => {
      const t0 = performance.now(); const p = s.lift == null ? 1 : Math.max(0, Math.min(1, s.lift));
      if (p <= 0) { clear(); last = s; return; }
      const want = nearest(s.w); if (!sets[want]) loadSet(want);
      const wsel = (sets[want] && sets[want].loaded) ? want : loadedNearest(s.w); if (wsel == null) { clear(); return; }   /* until the set's maps arrive: the nearest loaded */
      const st = sets[wsel]; const lw = s.w, lh = s.h, lx = s.cx - lw / 2, ly = s.cy - lh / 2;
      /* the wrapper snapped to the device pixel grid: pass 1's pixels then coincide with the canvas's, and pass 2's bilinear read of A lands on texel
         centres (no resampling blur of the copies; the fields still sample the textures at their fractional positions) */
      const wx = Math.floor((lx - AM) * DPR) / DPR, wy = Math.floor((ly - AM) * DPR) / DPR, ww = Math.ceil((lx + lw + AM) * DPR) / DPR - wx, wh_ = Math.ceil((ly + lh + AM) * DPR) / DPR - wy;
      const aw = Math.round(ww * DPR), ah = Math.round(wh_ * DPR); if (!A || A.w !== aw || A.h !== ah) { A = fbo(aw, ah); }
      gl.bindFramebuffer(gl.FRAMEBUFFER, A.f); gl.viewport(0, 0, A.w, A.h); useProg(P1);
      gl.uniform4f(U(P1, "u_quad"), wx, wy, ww, wh_); gl.uniform2f(U(P1, "u_origin"), wx, wy); gl.uniform2f(U(P1, "u_view"), ww, wh_);
      gl.uniform2f(U(P1, "u_page"), W, H); gl.uniform4f(U(P1, "u_lens"), lx, ly, lw, lh); gl.uniform1f(U(P1, "u_S"), st.S); gl.uniform1f(U(P1, "u_p"), p);
      bind(P1, "t_page", 0, tPage); bind(P1, "t_lab", 1, tLab); bind(P1, "m_bg", 2, st.bg); bind(P1, "m_lab", 3, st.lab); bind(P1, "t_ish", 4, st.ish.t);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      clear(); useProg(P2);
      gl.uniform4f(U(P2, "u_quad"), wx, wy, ww, wh_); gl.uniform2f(U(P2, "u_origin"), 0, 0); gl.uniform2f(U(P2, "u_view"), W, H);
      gl.uniform4f(U(P2, "u_lens"), lx, ly, lw, lh); gl.uniform4f(U(P2, "u_wrap"), wx, wy, ww, wh_); gl.uniform1f(U(P2, "u_Sab"), st.Sab); gl.uniform1f(U(P2, "u_wh"), s.wh || 1.72); gl.uniform1f(U(P2, "u_p"), p);
      gl.uniform2f(U(P2, "u_page"), W, H); gl.uniform1f(U(P2, "u_dbg"), opts.debugPass1 ? 1 : 0); bind(P2, "t_a", 0, A.t); bind(P2, "m_ab", 1, st.ab); bind(P2, "t_page", 2, tPage); bind(P2, "t_lab", 3, tLab); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (opts.finish) gl.finish();
      stats.gpuMs = performance.now() - t0; stats.frames++; stats.set = wsel; last = s;
    };
    return { gl, canvas, setState, redrawBackdrop, backdropCanvas: () => composite, stats, sets, loadSet, destroy: () => { gl.getExtension("WEBGL_lose_context")?.loseContext(); } };
  };
  /* the sets from the page's inline <svg>: #<prefix>-lens-f-bg-<w> (href, data-s), -lab-, -ab- (data-s) — the same files the SVG filters use; h from the map's pixel height / 2 is not known here: pass heights (view.js's series table) or let the page's set table carry them */
  const setsFromFilters = (prefix, heights) => { const out = {}; for (const f of document.querySelectorAll(`filter[id^="${prefix}-lens-f-bg-"]`)) { const w = parseInt(f.id.slice(`${prefix}-lens-f-bg-`.length), 10); if (!(w > 0)) continue;
      const href = (el) => el && (el.dataset.hrefOrig || el.getAttribute("href") || el.getAttributeNS("http://www.w3.org/1999/xlink", "href"));   /* data-href-orig: the file behind lens-engine-fix.js's blob: copy (the GPU path samples the plain map) */
      const bg = href(f.querySelector("feImage")), lab = href(document.querySelector(`#${prefix}-lens-f-lab-${w} feImage`)), fab = document.querySelector(`#${prefix}-lens-f-ab-${w}`), ab = href(fab && fab.querySelector("feImage"));
      if (!bg || !lab || !ab) continue; const S0 = parseFloat(f.dataset.s0 || f.dataset.s) || 40; const Sab = fab ? parseFloat(fab.dataset.s) || 12 : 12;
      out[w] = { bg, lab, ab, S: S0, Sab, h: heights && heights[w] ? heights[w] : null }; } return out; };
  window.LensWebGL = { create, setsFromFilters, VS, FS1, FS2, FS_ISH, COMMON };
})();
