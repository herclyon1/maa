/* lens-webgl.js — the lifted segment lens as a WebGL2 overlay (README §0.8.6 the chain, §0.8.7 the wiring). The ui session's interface (14:xx):
     const L = LensWebGL.create({ canvas, assets: "assets/lens/", set: 220, dpr: devicePixelRatio });   // the canvas = the wrapper (lens box ± 16 pt), the
                                                                                                          //   page positions / sizes it per frame like .stack; alpha on
     await L.ready;                                                                                       // shaders compiled, the set's three maps uploaded
     L.setBackdrop({ region: { x, y, w, h }, ink: [r, g, b], page: (ctx) => {…}, labels: (ctx) => {…} });   // 2D callbacks in PAGE pt: what lies under the lens
                                                                                                          //   without the labels / the labels alone; region = the part of the
                                                                                                          //   page the textures hold (the control's row ± the lens's reach); again
                                                                                                          //   when the value / theme / size changes
     L.draw({ lensX, lensY, w, h, p, pd, wh, platter: { rgba: [r, g, b, a], alpha } });                  // every frame — uniforms only; lensX/lensY = the lens box's page
                                                                                                          //   top-left, w × h = the model box (the nearest set), p = the glass
                                                                                                          //   progress (0 → nothing drawn), pd = the DestOut α (the capsule's
                                                                                                          //   alpha over the real content), wh = W/H (§3b.6), platter = the resting
                                                                                                          //   platter's colour (_controlForegroundColor) and its 1 − p; returns gpu ms
   (create(canvas, { sets, backdrop, ink, width, height, dpr }) + setState({ cx, cy, w, h, lift, wh }) + redrawBackdrop() — the harness's form — still work.)
   Warm-up: when `ready` resolves (and after each setBackdrop) one lifted frame is drawn through both passes and finished, never presented, so the
   first real glass frame does not pay the pipelines' and textures' first use (L.stats.warmMs; ?glwarm=0 / { warm: false } off).
   The canvas paints ONLY the capsule (the displaced copies, the label copy, the fringe, the highlight, the inner shadow) and, outside it, the
   glassBackground ring shadow (black α) + the KeyFill dark line's row (the page copy darkened) — everything else stays transparent, the live
   DOM shows through. What the taps read beyond the capsule comes from the backdrop textures the page draws.
   Sets: the map files of a width (the same files the SVG filters reference), S = data-s of the bg / lab filters (read off the page's inline <svg>
   when present, else 40), Sab = the fringe filter's (12), h = the set's height (from the map). LensWebGL.setsFromFilters("seg") builds the table.
   Chain and constants (their sources in the comments): pass 1 = the backdrop copy through the bg map with the DestOut punch, the ring shadow
   (keyfill §4), the built-in KeyFill dark line (keyfill §5.1), the label copy through the lab map clipped to the capsule, the inner shadow
   (keyfill §5.2c, precomputed per set); pass 2 = the 7-tap dispersion (formula §3b) over pass 1, the #36 highlight through the vibrant matrix
   (keyfill §2), the outside overlay. Maps sampled bilinearly, no engine correction (§0.8.6). Engine facts inside: an FBO's row 0 is the
   viewport's bottom (pass 2 reads pass 1 with a flipped t); macOS WebKit smooths canvas text only on an attached canvas (the scratch canvases
   are attached off-screen while drawn) and the labels' alpha is recovered from the opaque page / page + labels renders. */
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
uniform float u_rmax;   /* the capsule's corner radius cap: the segment lens 22 (DestOut cornerRadius stays 22 through the drag), the tab lens h/2 (tab-lens-native.md §0: cornerRadii 35 = 70/2 on every element) — opts.rmax */
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
uniform sampler2D t_page, t_lab, m_bg, m_lab, t_ish; uniform float u_lincomp; uniform vec4 u_page; /* the backdrop region x y w h, page pt */ uniform vec4 u_lens; uniform float u_S; uniform float u_p; uniform float u_pd; uniform vec4 u_platter; uniform float u_srcclip;
uniform float u_labmode; uniform vec2 u_model; uniform vec4 u_lst;   /* R37: 1 = the label field in float (below); u_model = the set's model box (pt); u_lst = the label stages in sampling order (amount, height)×2 */
/* compute_sdf_with_mode's gradient ovalization (formula §3; gen_lens_maps.py ovalized_gradient): g = normalize(mix(box normal, normalize((x, hw·y/hh)), .5)) — gradientOvalization .5 (seg-lens-refraction.md §1b 表 1 #13 / #19) */
uniform float u_sdfmode;   /* R38a: 0 = the rounded-box / capsule SDF (gen_lens_maps.py capsule_sdf); 1 = QuartzCore's supercircle branch (below) — opts.labelSdf / ?glsdf=super */
/* R38a — the element SDF as QuartzCore's uber shader computes it for equal corner radii (label-end-tear-closed-vs-map.md §7 ② IR 9455–9548 supercircle_sdf, §7b (a′)
   emit_sdf_bounds_internal 0x1c3a68628: clamp = sat(2.89158·(1 − hs/r)) per axis → (0, 0) for 220×44 r22, the supercircle branch): R = 1.528665·r; rr = mix(R, r, max(clamp));
   q = |p| − hs + rr; u = max(0, (|p| − hs + R)/R); ρ = min(u)/max(u); poly(ρ) = (((−.926054ρ + 3.15601)ρ − 3.64122)ρ + 1.26803)ρ + .268531; k = ρ²·sat(|u|)·poly;
   f_super = |u| + 1 − 1/(1 − k); f_circle = .6541656·|max(0, 1.528665u − .528665)| + .3458344; per axis mix by clamp, axis pick s = sat(.5 − sgn + sgn·ρ);
   d = R·(f − 1) + min(max(q), 0) (the IR truncates f − 1 to half: ≤ .016 pt, not applied); g = q.x + q.y > 0 ? normalize(max(0, q)) : the axis, sign-restored */
float scPoly(float rho){ return (((-0.926054 * rho + 3.15601) * rho - 3.64122) * rho + 1.26803) * rho + 0.268531; }
vec3 sdfSuper(vec2 p, vec2 hs, float r){
  float R = 1.528665 * abs(r); vec2 cl = clamp(2.89158 * (1.0 - hs / r), 0.0, 1.0); float rr = mix(R, abs(r), max(cl.x, cl.y));
  vec2 ap = abs(p); vec2 q = ap - hs + rr; vec2 u = max(vec2(0.0), (ap - hs + R) / R); float ul = length(u); float umax = max(u.x, u.y); float rho = umax > 0.0 ? sat(min(u.x, u.y) / umax) : 0.0;
  float k = rho * rho * sat(ul) * scPoly(rho); float fs = ul + 1.0 - 1.0 / (1.0 - k);
  vec2 v = max(vec2(0.0), 1.528665 * u - 0.528665); float fc = 0.6541656 * length(v) + 0.3458344;
  float fx = mix(fs, fc, cl.x), fy = mix(fs, fc, cl.y); float sg = u.y > u.x ? 1.0 : -1.0; float s = sat(0.5 - sg + sg * rho); float f = mix(fx, fy, s);
  float d = R * (f - 1.0) + min(max(q.x, q.y), 0.0);
  vec2 g = (q.x + q.y > 0.0) ? normalize(max(vec2(1e-9), q)) : ((q.x > q.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0)); g *= vec2(p.x >= 0.0 ? 1.0 : -1.0, p.y >= 0.0 ? 1.0 : -1.0);
  return vec3(d, g); }
vec3 elemSdf(vec2 pm, vec2 hm, float rr){ return u_sdfmode > 0.5 ? sdfSuper(pm, hm, rr) : vec3(sdf(pm, hm, rr), nrm(pm, hm, rr)); }
vec2 gOval(vec2 pm, vec2 hm, float rr){ vec2 nb = elemSdf(pm, hm, rr).yz; vec2 rv = vec2(pm.x, hm.x * pm.y / hm.y); float rn = length(rv); rv = rn > 0.0 ? rv / rn : rv; vec2 g = mix(nb, rv, 0.5); float gn = length(g); return gn > 0.0 ? g / gn : g; }
/* one displacement stage at the model point pm (formula §1: t = saturate(−d/H), 1 − P = 1 − sqrt(1 − (1 − t)²) (curvature 1, effectOffset 0, angle 0); §2: offset = amount × that × g; the coverage
   saturate(−d/fw + .5), fw = ⅓ pt, the map's B) → (offset.xy, cov) */
vec3 lstage(vec2 pm, vec2 hm, float rr, float amount, float height){ float d = elemSdf(pm, hm, rr).x; float t = sat(-d / height); float amp = amount * (1.0 - sqrt(sat(1.0 - (1.0 - t) * (1.0 - t)))); return vec3(amp * gOval(pm, hm, rr), sat(-d * 3.0 + 0.5)); }
vec4 page(vec2 p){ return texture(t_page, (p - u_page.xy) / u_page.zw); }
vec4 lab(vec2 p){ return texture(t_lab, (p - u_page.xy) / u_page.zw); }
vec4 over(vec4 s, vec4 d){ return s + d * (1.0 - s.a); }
vec3 linv(vec3 c){ return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }   /* sRGB → linear (IEC 61966-2-1), R38d */
vec3 encv(vec3 l){ return mix(l * 12.92, 1.055 * pow(max(l, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, l)); }
void main(){
  vec2 C = u_lens.xy + u_lens.zw * 0.5, half_ = u_lens.zw * 0.5; float r = min(u_rmax, half_.y);   /* the segment lens: r 22 clamped to h/2 (DestOut cornerRadius stays 22 through the drag) */
  vec2 pl = v - C; float d = sdf(pl, half_, r); vec2 n = nrm(pl, half_, r); float fwd = max(fwidth(d), 1e-4);
  float M = sat(0.5 - d / fwd);
  vec4 under = over(lab(v), page(v));
  vec2 uv = (v - u_lens.xy) / u_lens.zw; bool inBox = uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0;
  vec4 mb = inBox ? texture(m_bg, uv) : vec4(128.0 / 255.0, 128.0 / 255.0, 0.0, 1.0);
  vec2 ub = decode(mb.rg, u_S) * u_p; float covb = mb.b;
  vec2 qb = v + ub; float dq = sdf(qb - C, half_, r); float Mq = sat(0.5 - dq / max(fwidth(dq), 1e-4));
  vec4 bgc = over(lab(qb) * (1.0 - Mq * u_pd), page(qb));        /* layer 1 + DestOut #43: the segment content is removed inside the capsule at the SOURCE with the DestOut α (§4.1 .396 / .98 / 1 on the first three lift frames, then 1; formula §4b) — the punch fades the real labels out of the capture; the lens's own output is never scaled by it */
  vec4 col = mix(under, bgc, covb);
  col.rgb *= (1.0 - ringTerm(pl, half_, r) * u_p);               /* the ring shadow on the layer (inside; the outside part is the overlay of pass 2) */
  float k = darkLineK(d, n) * u_p; col.rgb = col.rgb * (1.0 + (-0.3) * k * (3.0 - 2.0 * col.rgb));   /* the dark line: rgb' = rgb·(1 + colorBias·k·(3 − 2·rgb)) */
  col.rgb = mix(col.rgb, u_platter.rgb, u_platter.a * covb);    /* the resting platter (restingBackground #5, _controlForegroundColor): above the displaced backdrop, below the lines and the labels, opacity 1 → 0 on the lift (§4b; the SVG page's .plat = 1 − lp) — u_platter = rgb × the page's alpha */
  vec4 ml = inBox ? texture(m_lab, uv) : vec4(128.0 / 255.0, 128.0 / 255.0, 0.0, 1.0);
  /* layers 2 + 4: the label copy — the portal #20 clips the segment content to the capsule BEFORE the displacement (masksToBounds 1, cornerRadii 22, seg-lens-refraction.md §1b
     table 2; the SVG page's .displ border-radius before its filter: 先裁再位移), so a sample that lands outside the capsule reads transparent (the tearing at the ends); the map's B =
     the two stages' own masks (compose_stages); the destination is not clipped again (portal #32 masksToBounds 0, §4b) */
  vec2 ul; float Bl;
  if (u_labmode > 0.5) {   /* R37: the two stages evaluated here in float at every pixel instead of the 8-bit 2 px/pt map (formula §1 sdf_glass_displacement + §2 displacement_map_lpf, composed as
                              gen_lens_maps.py compose_stages: model point pm = pl / S with S = the presented box ÷ the model box (u(p) = S·u₀(S⁻¹p), seg-lens-refraction.md §1c(d)); stage i: cov at its own
                              pixel (fw = ⅓ pt, the native 3× device pixel), then pm += amount·(1 − P)·g_oval, then the clamp to the last texel centre (½ device px = ⅙ pt, §4b.1 A); the amounts ride the
                              lift (the material spring animates the amount keys, seg-lens-refraction.md §4.4); B = the coverages' product = the map's B) */
    vec2 hm = u_model * 0.5; float rm = min(u_rmax, hm.y); vec2 Sc = u_lens.zw / u_model; vec2 pm = pl / Sc; vec2 lim = hm - vec2(1.0 / 6.0); float B = 1.0;
    vec3 s1 = lstage(pm, hm, rm, u_lst.x * u_p, u_lst.y); B *= s1.z; pm = clamp(pm + s1.xy, -lim, lim);
    vec3 s2 = lstage(pm, hm, rm, u_lst.z * u_p, u_lst.w); B *= s2.z; pm = clamp(pm + s2.xy, -lim, lim);
    ul = pm * Sc - pl; Bl = B;
  } else { ul = decode(ml.rg, u_S) * u_p; Bl = ml.b; }
  vec2 ql = v + ul; float dl = (u_sdfmode > 0.5 && u_labmode > 0.5) ? sdfSuper((ql - C) / (u_lens.zw / u_model), u_model * 0.5, min(u_rmax, u_model.y * 0.5)).x : sdf(ql - C, half_, r); float Ml = sat(0.5 - dl / max(fwidth(dl), 1e-4));   /* R38a: the portal's clip in the element's shape (model coords in super mode) */
  vec4 lc = lab(ql) * (u_srcclip > 0.5 ? Ml : 1.0) * Bl;   /* u_srcclip: the #20 clip at the sampled position (1, the read chain); 0 = the destination clip only (before d3a6dce), an instrument */
  /* R38d (老网页 R99, label-end-tear §7g): the label copy meets the glass background in #33's LINEAR-light source surface — L′ = enc(lin(bg)·(1 − c) + lin(ink)·c), not the sRGB
     over: the same coverage c darkens less, so near-threshold ink drops out (drag-mid, three fields + aberration off: model 799 / 286 vs native 807 / 279 against the sRGB
     composite's 1018 / 385). u_lincomp 1 (default; ?gllin=0 = the sRGB over of before) */
  if (u_lincomp > 0.5 && lc.a > 1e-6) { vec3 ic = lc.rgb / lc.a; vec3 l = linv(ic) * lc.a + linv(col.rgb) * (1.0 - lc.a); col = vec4(encv(l), 1.0); } else col = over(lc, col);
  float ish = inBox ? texture(t_ish, vec2(uv.x, 1.0 - uv.y)).r : 0.0; col.rgb *= (1.0 - ish * u_p);   /* inner shadow #21 (keyfill §5.2c); t_ish is an FBO (row 0 = bottom) */
  o = vec4(col.rgb, 1.0);
}`;
  const FS_ISH = `#version 300 es
${COMMON}
in vec2 v; out vec4 o; uniform vec4 u_lens;
float Mh(vec2 p, vec2 half_, float r){ return sdf(p, half_, r) <= 0.0 ? 1.0 : 0.0; }
void main(){ vec2 C = u_lens.xy + u_lens.zw * 0.5, half_ = u_lens.zw * 0.5; float r = min(u_rmax, half_.y); vec2 p = v - C;
  float sig = 3.0, off = 7.0, op = 0.06; float acc = 0.0, wsum = 0.0;   /* keyfill §5.2c: op · M · blur_σ(M − M↓off), σ = shadowRadius 3, offset (0, 7), shadowOpacity .06 */
  for (int i = -9; i <= 9; i++) for (int j = -9; j <= 9; j++) { vec2 k = vec2(float(i), float(j)); float w = exp(-dot(k, k) / (2.0 * sig * sig)); wsum += w; vec2 q = p + k; acc += w * Mh(q, half_, r) * (1.0 - Mh(q - vec2(0.0, off), half_, r)); }
  float d = sdf(p, half_, r); float M = sat(0.5 - d / max(fwidth(d), 1e-4));
  o = vec4(op * M * acc / wsum, 0.0, 0.0, 1.0); }`;
  const FS2 = `#version 300 es
${COMMON}
in vec2 v; out vec4 o;
uniform sampler2D t_a, m_ab, t_page, t_lab; uniform vec4 u_page; uniform vec4 u_lens; uniform vec4 u_wrap; uniform float u_Sab; uniform float u_wh; uniform float u_p; uniform float u_pd; uniform float u_dbg; uniform float u_ab;   /* u_ab: ?glab= instrument bits (R8 device A/B): 1 = the outside dark line off, 2 = the outside ring off, 4 = the dispersion taps off */
uniform vec2 u_ascale; /* the wrapper's share of the (larger, once-allocated) FBO */
vec4 A(vec2 p){ vec2 t = (p - u_wrap.xy) / u_wrap.zw; return texture(t_a, vec2(t.x * u_ascale.x, (1.0 - t.y) * u_ascale.y)); }   /* an FBO's row 0 is the viewport's bottom: page-down y → flipped t */
vec4 over(vec4 s, vec4 d){ return s + d * (1.0 - s.a); }
vec3 linv(vec3 c){ return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }   /* sRGB → linear (IEC 61966-2-1), R38d */
vec3 encv(vec3 l){ return mix(l * 12.92, 1.055 * pow(max(l, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, l)); }
vec3 V(vec3 b){ return min(vec3(1.0), 0.9118 * b + 0.1471); }   /* vibrantColorMatrix on the layer's α (keyfill §2) */
float band(float e, float h, float cosS, float bias, float curv, vec2 n, vec2 dir, float fw){
  float t = sat(e / h); float prof = mix(t < 1.0 ? 1.0 : 0.0, 1.0 - t, curv); float aa = sat(e / fw + 0.5) * sat((h - e) / fw + 0.5);
  float ang = sat((dot(n, dir) - cosS) / (1.0 - cosS)); float vv = (e < -5.0) ? 0.0 : prof * aa * ang; return vv / (1.0 + bias * (1.0 - vv)); }
void main(){
  vec2 C = u_lens.xy + u_lens.zw * 0.5, half_ = u_lens.zw * 0.5; float r = min(u_rmax, half_.y);
  vec2 pl = v - C; float d = sdf(pl, half_, r); vec2 n = nrm(pl, half_, r); float fw = max(fwidth(d), 1e-4); float M = sat(0.5 - d / fw);
  vec4 below = A(v);
  vec2 wuv = (v - u_wrap.xy) / u_wrap.zw; vec4 ma = texture(m_ab, wuv);
  vec2 D = decode(ma.rg, u_Sab) * vec2(u_wh, 1.0 / u_wh) * u_p * (mod(floor(u_ab / 4.0), 2.0) > 0.5 ? 0.0 : 1.0); float e = ma.b * ma.a * u_p * (mod(floor(u_ab / 4.0), 2.0) > 0.5 ? 0.0 : 1.0); float edr = 1.0;   /* formula §3b.3 / 3b.5: Δ × (W/H, H/W), e = the envelope × cov */
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
  float ring = ringTerm(pl, half_, r) * u_p * (mod(floor(u_ab / 2.0), 2.0) > 0.5 ? 0.0 : 1.0); float k = darkLineK(d, n) * u_p * (mod(u_ab, 2.0) > 0.5 ? 0.0 : 1.0);
  vec4 und = over(texture(t_lab, (v - u_page.xy) / u_page.zw), texture(t_page, (v - u_page.xy) / u_page.zw));
  vec3 f = (1.0 + (-0.3) * k * (3.0 - 2.0 * und.rgb)) * (1.0 - ring);   /* the darkening the two outside terms apply to the colour under them (keyfill §5.1 / §4), taken from the copy's colour there */
  float aOut = 1.0 - (f.r + f.g + f.b) / 3.0;                            /* painted as black α over the live DOM — nothing of the copy is drawn outside the capsule (界面1号 ⑤) */
  vec4 outside = vec4(0.0, 0.0, 0.0, sat(aOut));
  o = mix(outside, vec4(col, 1.0), M);   /* inside the capsule the lens's output, opaque (the DestOut α acts on the copy's source in pass 1 — a20df11's first lift frames lost the platter because the whole capsule was × pd here) */
}`;
  const loadImg = (src) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("lens-webgl: " + src)); i.src = src; });
  const create = (canvasOrOpts, opts0) => {
    const uiForm = !(canvasOrOpts instanceof HTMLCanvasElement); const opts = uiForm ? canvasOrOpts : (opts0 || {}); const canvas = uiForm ? opts.canvas : canvasOrOpts;
    const gl = canvas.getContext("webgl2", { antialias: false, premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: !!opts.preserve });
    if (!gl) return null;
    const DPR = opts.dpr || window.devicePixelRatio || 1, AM = opts.margin || 16;
    /* the ui form: the canvas is the wrapper (lens ± 16), moved and sized by the page per frame; its pt size follows draw()'s w / h */
    let W = opts.width || canvas.clientWidth || parseFloat(canvas.style.width) || canvas.width, H = opts.height || canvas.clientHeight || parseFloat(canvas.style.height) || canvas.height;   /* the canvas in pt */
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    if (uiForm && !opts.sets) { const w0 = opts.set || 220, base = opts.assets != null ? opts.assets : "assets/lens/", fromSvg = setsFromFilters("seg"); opts.sets = Object.keys(fromSvg).length ? fromSvg : { [w0]: { bg: `${base}seg-f-bg-${w0}.png`, lab: `${base}seg-f-lab-${w0}.png`, ab: `${base}seg-f-ab-${w0}.png`, S: 40, Sab: 12 } }; opts.preload = [w0]; }
    if (uiForm) {   /* the backing store is allocated ONCE at the largest wrapper the sets can need (a per-frame canvas.width change reallocates the buffer — the lift's bounds change every frame); the page sets the element's left/top only, its CSS size is fixed here */
      const ws = Object.keys(opts.sets).map(Number); const maxW = (opts.maxSize && opts.maxSize[0]) || Math.max(...ws) + 2 * AM, maxH = (opts.maxSize && opts.maxSize[1]) || 48 + 2 * AM;   /* 48: the tallest stretch set's height (256 → 48.5, lens-field.json) */
      W = maxW; H = maxH; canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR); canvas.style.width = W + "px"; canvas.style.height = H + "px"; }
    if (!opts.backdrop) opts.backdrop = () => {};   /* set later by setBackdrop */
    let region = opts.region || { x: 0, y: 0, w: W, h: H };   /* the page rectangle the backdrop textures hold, page pt */
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const prog = (vs, fs) => { const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p; };
    const stats = { gpuMs: 0, frames: 0, set: 0, prewarm: {} };   /* + labMode / rmax / labelStages (R37) once the constants below are known */
    const tC0 = performance.now(); const P1 = prog(VS, FS1), PISH = prog(VS, FS_ISH), P2 = prog(VS, FS2); stats.prewarm.compileMs = performance.now() - tC0;   /* shader compile + link (the drivers may still defer the pipeline until the first draw: the warm draw below) */
    const quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    const useProg = (p) => { gl.useProgram(p); const a = gl.getAttribLocation(p, "a"); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0); };
    const U = (p, name) => gl.getUniformLocation(p, name);
    const tex = (src, premul) => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, !!premul); gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src); for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v); return t; };
    const fbo = (w, h) => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null); for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
      const f = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, f); gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t, 0); gl.bindFramebuffer(gl.FRAMEBUFFER, null); return { t, f, w, h }; };
    const bind = (p, name, unit, t) => { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t); gl.uniform1i(U(p, name), unit); };
    /* the backdrop textures: the page draws them (canvas pt) */
    /* the labels texture is NOT drawn on a transparent canvas: on macOS WebKit text over a transparent backdrop gets no font smoothing (thinner
       stems than the same text on the page — measured: the glyph's ink box 108.5–131.33 vs the page's 107.67–132). The page draws the labels OVER
       the page copy (opaque, smoothed like the DOM text), and the labels' alpha is recovered per pixel from the two opaque images:
       P = Pg·(1 − a) + ink·a → a = (P − Pg)/(ink − Pg) (opts.ink = the label colour; the channel with the largest |ink − Pg| decides) */
    /* the scratch canvases are attached to the document (off-screen) and kept: macOS WebKit smooths text on an attached canvas like the DOM's text
       and not on a detached one (measured: the same 13 px glyph's ink box 107.67–132 attached / DOM vs 108.5–131.33 detached); iOS renders both alike */
    const scratch = document.createElement("div"); scratch.style.cssText = "position:absolute;left:-100000px;top:0;width:1px;height:1px;overflow:hidden;pointer-events:none"; document.body.appendChild(scratch);
    const sc = { pg: null, p: null, w: 0, h: 0 };
    const scratchCanvases = () => { const w = Math.round(region.w * DPR), h = Math.round(region.h * DPR); if (sc.w !== w || sc.h !== h) { for (const k of ["pg", "p"]) { if (sc[k]) sc[k].remove(); const c = document.createElement("canvas"); c.width = w; c.height = h; c.style.cssText = `width:${region.w}px;height:${region.h}px`; scratch.appendChild(c); sc[k] = c; } sc.w = w; sc.h = h; } return sc; };
    const draw2d = (c, which, labelsFn) => { const x = c.getContext("2d", { willReadFrequently: true }); x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, c.width, c.height); x.scale(DPR, DPR); x.translate(-region.x, -region.y); const info = { width: W, height: H, region }; opts.backdrop(x, "page", info); if (which === "labels") (labelsFn || ((xx, ii) => opts.backdrop(xx, "labels", ii)))(x, info); return c; };
    /* the labels' alpha per pixel from the two opaque renders: P = Pg·(1 − a) + ink·a → a = (P − Pg)/(ink − Pg); the ink = the colour of the pixel the labels changed most
       (opts.ink is used only when within 48 levels of it — a wrong ink, the light theme's black in the dark theme, empties thin strokes' alpha) */
    let labImg = null;
    const labelsAlpha = (cPg, cP) => { const w = cPg.width, h = cPg.height; const a = cPg.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, w, h).data, b = cP.getContext("2d", { willReadFrequently: true }).getImageData(0, 0, w, h).data;
      let best = -1, det = [0, 0, 0]; for (let i = 0; i < a.length; i += 4) { const dd = Math.abs(b[i] - a[i]) + Math.abs(b[i + 1] - a[i + 1]) + Math.abs(b[i + 2] - a[i + 2]); if (dd > best) { best = dd; det = [b[i], b[i + 1], b[i + 2]]; } }
      const given = opts.ink && opts.ink.length === 3 ? opts.ink.map(Number) : null; const ink = (given && Math.abs(given[0] - det[0]) + Math.abs(given[1] - det[1]) + Math.abs(given[2] - det[2]) <= 48) ? given : det; stats.ink = ink;
      if (!labImg || labImg.width !== w || labImg.height !== h) labImg = new ImageData(w, h); const o = labImg.data;
      for (let i = 0; i < a.length; i += 4) {
        if (b[i] === a[i] && b[i + 1] === a[i + 1] && b[i + 2] === a[i + 2]) { o[i] = 0; o[i + 1] = 0; o[i + 2] = 0; o[i + 3] = 0; continue; }   /* untouched by the labels: α 0 (most pixels) */
        let bestd = 0, al = 0; for (let c = 0; c < 3; c++) { const den = ink[c] - a[i + c]; if (Math.abs(den) > Math.abs(bestd)) { bestd = den; al = (b[i + c] - a[i + c]) / den; } }
        al = al < 0 ? 0 : al > 1 ? 1 : al; o[i] = ink[0] * al; o[i + 1] = ink[1] * al; o[i + 2] = ink[2] * al; o[i + 3] = al * 255; }
      return labImg; };
    const upload = (t, src, premul) => { gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, !!premul); gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src); };
    let tPage = null, tLab = null, liveLab = null, composite = null, redrawPending = 0;
    const measure = (name, t0) => { try { performance.measure(name, { start: t0, end: performance.now() }); } catch (e) { /* older engines */ } };   // seg:gl-* rows for the frames recorder
    /* opts.labelsDirect: the labels callback draws them with their own alpha on a cleared canvas (icons of any colour, several inks) — uploaded as they are;
       otherwise (the segment control: one ink, the page drawn opaque) the alpha is recovered from the two renders (labelsAlpha) */
    const drawLabelsDirect = (c) => { const x = c.getContext("2d", { willReadFrequently: true }); x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, c.width, c.height); x.scale(DPR, DPR); x.translate(-region.x, -region.y); opts.backdrop(x, "labels", { width: W, height: H, region }); return c; };
    const redrawNow = () => { const tb = performance.now(); const { pg, p: cP } = scratchCanvases(); draw2d(pg, "page"); if (opts.labelsDirect) drawLabelsDirect(cP); else draw2d(cP, "labels"); const t1 = performance.now();
      const li = opts.labelsDirect ? cP : labelsAlpha(pg, cP); const t2 = performance.now();
      if (!tPage) { tPage = tex(pg, true); liveLab = tex(li, true); } else { upload(tPage, pg, true); upload(liveLab, li, true); }
      tLab = liveLab; variants.clear(); stats.labels = "live";   // the page changed under the lens: every prepared variant is stale (the page prepares again at idle)
      composite = cP; stats.prewarm.backdropMs = performance.now() - tb; stats.prewarm.backdropDrawMs = t1 - tb; stats.prewarm.backdropAlphaMs = t2 - t1; stats.prewarm.backdropUploadMs = performance.now() - t2; measure("seg:gl-redraw", tb); };
    /* label variants (BOARD R31 — the first gesture's down frame on the phone held ~40 ms of backdrop redraw, README §0.8.11 ③): the labels texture for a
       given selection is prepared at idle — the page drawn once more into the page canvas, the labels with the caller's own callback (the page draws them
       with that selection's weight), the alpha recovered, uploaded into a texture kept under `key` — and switched at the down with useLabels(key): a
       variable assignment, no 2D draw, no alpha pass, no upload, no warm-up (the pipeline and the texture object are already resident). The live texture
       (redrawNow / redrawBackdrop) stays; a redraw drops every variant — the page prepares them again at idle after a render or a theme change.
       Wiring (view.js, the ui session): at idle after the prewarm, for every segment i: lens.prepareLabels(i, (x, info) => <the labels with i selected>);
       at the down on segment p: lens.useLabels(p) (instead of the futureOn redraw); at the commit the selection is p, so the bound texture already matches. */
    const variants = new Map();
    const prepareLabels = (key, labelsFn) => { const t0 = performance.now(); if (typeof labelsFn !== "function") return false; const { pg, p: cP } = scratchCanvases(); draw2d(pg, "page"); draw2d(cP, "labels", labelsFn);
      const li = labelsAlpha(pg, cP); let v = variants.get(key); if (!v) { v = { t: tex(li, true) }; variants.set(key, v); } else upload(v.t, li, true);
      measure("seg:gl-prepare", t0); return true; };
    const useLabels = (key) => { const v = variants.get(key); if (!v) return false; tLab = v.t; stats.labels = key; return true; };
    const hasLabels = (key) => variants.has(key);
    /* redrawBackdrop(): by default the work is deferred to the next task (setTimeout 0) so that a value flip's redraw does not land inside the gesture's
       first glass frame (the tap path: commit → render → the first lens frame — the data session read 47–50 ms there); the frames until then draw with
       the previous textures (the native crossfades the label's weight / contents over 0.2 s anyway, seg-lens-refraction §4.4); { sync: true } draws now */
    const redrawBackdrop = (o) => { if (o && o.sync) { redrawNow(); return; } if (redrawPending) return; redrawPending = setTimeout(() => { redrawPending = 0; const t0 = performance.now(); redrawNow(); if (typeof warm === "function") warm(); measure("seg:gl-redraw-task", t0); }, 0); };
    redrawNow();
    /* the sets: maps per width, textures loaded on first use; the inner shadow per set */
    const sets = {}; const widths = Object.keys(opts.sets).map(Number).sort((a, b) => a - b);
    const nearest = (w) => { let best = widths[0], dd = Infinity; for (const x of widths) { const d = Math.abs(x - w); if (d < dd) { dd = d; best = x; } } return best; };
    const ISH_PX = 3;
    const loadSet = (w) => { if (sets[w]) return sets[w].ready; const s = opts.sets[w]; const st = sets[w] = { S: s.S || 40, Sab: s.Sab || 12, h: s.h, bg: null, lab: null, ab: null, ish: null, ready: null };
      st.ready = Promise.all([loadImg(s.bg), loadImg(s.lab), loadImg(s.ab)]).then(([a, b, c]) => { const tm = performance.now(); st.bg = tex(a); st.lab = tex(b); st.ab = tex(c); stats.prewarm["mapsMs_" + w] = performance.now() - tm; if (!st.h) st.h = a.height / (a.width / w);   /* the bg map covers the lens box: h = its height at the map's px/pt */
        st.ish = fbo(Math.round(w * ISH_PX), Math.round(st.h * ISH_PX)); gl.bindFramebuffer(gl.FRAMEBUFFER, st.ish.f); gl.viewport(0, 0, st.ish.w, st.ish.h); useProg(PISH);
        const ti = performance.now(); gl.uniform1f(U(PISH, "u_rmax"), RMAX); gl.uniform4f(U(PISH, "u_lens"), 0, 0, w, st.h); gl.uniform4f(U(PISH, "u_quad"), 0, 0, w, st.h); gl.uniform2f(U(PISH, "u_origin"), 0, 0); gl.uniform2f(U(PISH, "u_view"), w, st.h); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); if (w === (preload[0] || 220)) gl.finish(); gl.bindFramebuffer(gl.FRAMEBUFFER, null); stats.prewarm["ishMs_" + w] = performance.now() - ti; st.loaded = true; });
      return st.ready; };
    const loadedNearest = (w) => { const cands = widths.filter((x) => sets[x] && sets[x].loaded); if (!cands.length) return null; let best = cands[0], dd = Infinity; for (const x of cands) { const d = Math.abs(x - w); if (d < dd) { dd = d; best = x; } } return best; };
    const preload = opts.preload || [widths.includes(220) ? 220 : widths[0]]; for (const w of preload) loadSet(w);
    let A = null, B = null, drawn = false;   /* A: pass 1's target; B: a warm-up's pass-2 target (canvas-sized, never presented); drawn: the page has drawn or cleared the canvas itself */
    const clear = () => { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, canvas.width, canvas.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); };
    let canvasOrigin = { x: 0, y: 0 };   /* the canvas's page position (the ui form moves the canvas with the lens) */
    const setState = (s) => {
      const t0 = performance.now(); const p = s.lift == null ? 1 : Math.max(0, Math.min(1, s.lift)), pd = s.pd == null ? 1 : Math.max(0, Math.min(1, s.pd));
      if (s.canvasOrigin) canvasOrigin = s.canvasOrigin;
      if (p <= 0) { clear(); drawn = true; stats.last = { lift: 0, pd, platterAlpha: 0, platterColorAlpha: 0, t: performance.now() }; return; }   /* rest is the PAGE's call (lift 0 from its clear()), never the package's: while the page keeps .lift the DOM platter is transparent and the canvas is the only platter — a package-side bound (b313aed's .001 / fb84a7e's .005) cleared the canvas 22 ticks before the page's clear and the white capsule vanished for 367 ms at the end of every tap (190821, README §0.8.12) */
      const base = preload[0] || 220;
      const want = s.w <= base ? base : nearest(s.w);   /* the lift (196×28 → 220×44) rides the 220 set stretched over the growing box (README §0.3, the SVG page's rule); only the drag stretch (> 220) has its own sets */
      if (!sets[want]) loadSet(want);
      const wsel = (sets[want] && sets[want].loaded) ? want : loadedNearest(s.w); if (wsel == null) { clear(); return; }   /* until the set's maps arrive: the nearest loaded */
      const st = sets[wsel]; const lw = s.w, lh = s.h, lx = s.cx - lw / 2, ly = s.cy - lh / 2;
      /* the wrapper snapped to the device pixel grid: pass 1's pixels then coincide with the canvas's, and pass 2's bilinear read of A lands on texel
         centres (no resampling blur of the copies; the fields still sample the textures at their fractional positions) */
      const wx = Math.floor((lx - AM) * DPR) / DPR, wy = Math.floor((ly - AM) * DPR) / DPR, ww = Math.ceil((lx + lw + AM) * DPR) / DPR - wx, wh_ = Math.ceil((ly + lh + AM) * DPR) / DPR - wy;
      const aw = Math.round(ww * DPR), ah = Math.round(wh_ * DPR); if (!A || A.w < aw || A.h < ah) { const t = performance.now(); A = fbo(Math.max(aw, canvas.width), Math.max(ah, canvas.height)); stats.prewarm.fboMs = performance.now() - t; }   /* once, at the canvas size */
      const TR = opts.trace || TRACE; const tr = TR ? { t0: performance.now() } : null; const mark = (k) => { if (!tr) return; gl.finish(); tr[k] = +(performance.now() - tr.t0).toFixed(2); };
      gl.bindFramebuffer(gl.FRAMEBUFFER, A.f); gl.viewport(0, 0, aw, ah); useProg(P1); mark("bindFbo_useP1");
      gl.uniform4f(U(P1, "u_quad"), wx, wy, ww, wh_); gl.uniform2f(U(P1, "u_origin"), wx, wy); gl.uniform2f(U(P1, "u_view"), ww, wh_);
      gl.uniform4f(U(P1, "u_page"), region.x, region.y, region.w, region.h); gl.uniform4f(U(P1, "u_lens"), lx, ly, lw, lh); gl.uniform1f(U(P1, "u_S"), st.S * FIELDS); gl.uniform1f(U(P1, "u_p"), p);
      gl.uniform1f(U(P1, "u_srcclip"), opts.srcClip === false ? 0 : 1); gl.uniform1f(U(P1, "u_lincomp"), LINCOMP); gl.uniform1f(U(P1, "u_pd"), pd);
      gl.uniform1f(U(P1, "u_rmax"), RMAX); gl.uniform1f(U(P1, "u_labmode"), LABMODE); gl.uniform1f(U(P1, "u_sdfmode"), SDFMODE); const mdl = st.model || opts.model || [220, 44]; gl.uniform2f(U(P1, "u_model"), mdl[0], mdl[1]); gl.uniform4f(U(P1, "u_lst"), LST[0], LST[1], LST[2], LST[3]);
      const pl_ = s.platter || { rgba: [0, 0, 0, 0], alpha: 0 }; gl.uniform4f(U(P1, "u_platter"), (pl_.rgba[0] || 0) / 255, (pl_.rgba[1] || 0) / 255, (pl_.rgba[2] || 0) / 255, (pl_.rgba[3] == null ? 1 : pl_.rgba[3]) * (pl_.alpha == null ? 1 : pl_.alpha));
      bind(P1, "t_page", 0, tPage); bind(P1, "t_lab", 1, tLab); bind(P1, "m_bg", 2, st.bg); bind(P1, "m_lab", 3, st.lab); bind(P1, "t_ish", 4, st.ish.t); mark("uniforms_binds1");
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); mark("pass1");
      if (s._split) { gl.finish(); stats._p1 = performance.now() - t0; }
      if (s._prewarm) { if (!B || B.w !== canvas.width || B.h !== canvas.height) B = fbo(canvas.width, canvas.height); gl.bindFramebuffer(gl.FRAMEBUFFER, B.f); gl.viewport(0, 0, canvas.width, canvas.height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); }   /* a warm-up's pass 2 lands in B, never on the canvas */
      else clear();
      useProg(P2); mark("clear_useP2");
      gl.uniform4f(U(P2, "u_quad"), wx, wy, ww, wh_); gl.uniform2f(U(P2, "u_origin"), canvasOrigin.x, canvasOrigin.y); gl.uniform2f(U(P2, "u_view"), W, H);
      gl.uniform1f(U(P2, "u_rmax"), RMAX); gl.uniform4f(U(P2, "u_lens"), lx, ly, lw, lh); gl.uniform4f(U(P2, "u_wrap"), wx, wy, ww, wh_); gl.uniform1f(U(P2, "u_Sab"), st.Sab); gl.uniform1f(U(P2, "u_wh"), s.wh || 1.72); gl.uniform1f(U(P2, "u_p"), p);
      gl.uniform4f(U(P2, "u_page"), region.x, region.y, region.w, region.h); gl.uniform1f(U(P2, "u_pd"), pd); gl.uniform1f(U(P2, "u_dbg"), opts.debugPass1 ? 1 : 0); gl.uniform1f(U(P2, "u_ab"), AB); gl.uniform2f(U(P2, "u_ascale"), aw / A.w, ah / A.h); bind(P2, "t_a", 0, A.t); bind(P2, "m_ab", 1, st.ab); bind(P2, "t_page", 2, tPage); bind(P2, "t_lab", 3, tLab); mark("uniforms_binds2"); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); mark("pass2");
      if (tr) { tr.set = wsel; tr.total = +(performance.now() - tr.t0).toFixed(2); stats.trace = tr; (stats.traces = stats.traces || []).push(tr); if (stats.traces.length > 60) stats.traces.shift(); }
      if (opts.finish || s._split) gl.finish();
      if (s._split) stats._p2 = performance.now() - t0 - stats._p1;
      stats.gpuMs = performance.now() - t0; stats.frames++; stats.set = wsel; if (!s._prewarm) { drawn = true; stats.last = { lift: p, pd, platterAlpha: pl_.alpha == null ? 1 : pl_.alpha, platterColorAlpha: pl_.rgba[3] == null ? 1 : pl_.rgba[3], t: performance.now() }; }   /* platterAlpha = the page's fade (1 − p); the token's own alpha (dark (235,235,245,.3)) is separate */   /* stats.last: what the frame drew (R7's row reads the platter's alpha against 1 − lift) */
    };
    /* warm-up (监督局 14:4x: the page's first glass frame stalled 46–55 ms — the shader pipelines and the textures were first used on that frame): after the
       preloaded set is up, one lifted frame is drawn through both passes — pass 1 into A, pass 2 into B (a canvas-sized FBO): the canvas is never drawn by a
       warm-up, so no warm-up frame can be presented or left behind — then gl.finish(); again after every setBackdrop / redrawBackdrop (the new textures'
       first use). ?glwarm=0 / opts.warm === false skips it. */
    const WARM = opts.warm !== false && new URLSearchParams(location.search).get("glwarm") !== "0";
    /* R8 device A/B (instrument, default 0 = nothing off): ?glab=nodark2,noring2,nofringe — the outside dark line / the outside ring / the dispersion taps
       of pass 2, to tell on the device which term makes the right end's line 3× deeper and 2 pt wide (README §0.8.8 ③; not reproduced on the Mac) */
    const AB = (() => { const q = (new URLSearchParams(location.search).get("glab") || (opts.ab || "")).split(","); return (q.includes("nodark2") ? 1 : 0) + (q.includes("noring2") ? 2 : 0) + (q.includes("nofringe") ? 4 : 0); })();
    /* R37 (formula.md §3b.9): the label copy's field per pixel in float — opts.labMode "closed" | "map", ?gllab=closed|map overrides; default "closed" */
    const LABMODE = (() => { const q = new URLSearchParams(location.search).get("gllab"); const m = q || opts.labMode || "closed"; return m === "map" ? 0 : 1; })();
    const SDFMODE = (() => { const q = new URLSearchParams(location.search).get("glsdf"); const m = q || opts.labelSdf || "super"; return m === "circle" ? 0 : 1; })();   /* R38a / NATIVE-GAP G25: the element SDF of the float label field (the label stages and the portal clip only; the backdrop path stays on the capsule maps, label-end-tear §7e) — default "super" = QuartzCore's equal-radius branch, the one the element takes (emit_sdf_bounds_internal 0x1c3a686cc: image function 21 = supercircle_sdf_image<false>, §7b (a′)); ?glsdf=circle = the half-disc capsule (instrument). The end-ink gap it left (78.6 vs 68 %, §7c) is the lifted state's dispersion and linear-light composite, now R38c / R38d */
    const RMAX = opts.rmax != null ? opts.rmax : 22;   /* the capsule's corner radius cap (seg 22; the tab family passes 1e6 = h/2) */
    const LINCOMP = new URLSearchParams(location.search).get("gllin") === "0" ? 0 : 1;   /* R38d: the label copy composited in linear light inside the lens (R99); ?gllin=0 = the sRGB over (instrument) */
    const FIELDS = new URLSearchParams(location.search).get("glfields") === "0" ? 0 : 1;   /* R38c instrument: ?glfields=0 = the three displacement fields off (the label stages' amounts and the maps' S → 0), the dispersion / highlight / lines untouched — the state of 数据's R95 / R98 measurements */
    const LST = (opts.labelStages || [-8.8, 7.04, -17.5, 11.2]).map((v, i) => (i % 2 === 0 ? v * FIELDS : v));   /* the label stack in sampling order: ContentLensing −8.8 / SDF height 7.04, then ClearGlass −17.5 / 11.2 (seg-lens-refraction.md §1b 表 1 #18 / #30, A9 原值) */
    stats.labMode = LABMODE ? "closed" : "map"; stats.rmax = RMAX; stats.labelStages = [...LST]; stats.labelSdf = SDFMODE ? "super" : "circle"; stats.fields = FIELDS; stats.linComp = LINCOMP;
    const TRACE = new URLSearchParams(location.search).get("gltrace") === "1";   /* per-step gl.finish timing of every frame into stats.trace / stats.traces (last 60) — an instrument, slows the frame */
    /* prewarm = one full lifted frame (the preloaded set, lift 1, pd 1, the current backdrop textures) through pass 1 (FBO A) and pass 2 (FBO B), gl.finish after
       each; the canvas is cleared only on an instance's first warm-up (the cleared buffer is what the compositor presents: the layer's display surface gets allocated); the per-step
       ms land in stats.prewarm (compileMs at create, mapsMs per set upload, ishMs, fboMs at the first draw, pass1Ms, pass2Ms, clearMs, totalMs) */
    const prewarm = () => { if (!WARM) return null; const w0 = loadedNearest(preload[0] || 220); if (w0 == null) return null; const st = sets[w0]; const T = performance.now();
      const t1 = performance.now(); setState({ cx: AM + w0 / 2, cy: AM + st.h / 2, w: w0, h: st.h, lift: 1, pd: 1, wh: 1.72, canvasOrigin: { x: 0, y: 0 }, _split: true, _prewarm: true }); stats.prewarm.pass1Ms = stats._p1; stats.prewarm.pass2Ms = stats._p2;
      /* the canvas is not touched by a warm-up (its pass 2 went into B): whatever the page last drew or cleared stays; the one exception is the first warm-up of
         an instance the page has not drawn yet — a clear then, so the canvas's display surface is allocated before the first gesture */
      const t3 = performance.now(); if (!drawn) clear(); gl.finish(); stats.prewarm.clearMs = performance.now() - t3; stats.prewarm.totalMs = performance.now() - T; stats.prewarm.at = performance.now(); stats.warmMs = stats.prewarm.totalMs;
      return stats.prewarm; };
    const warm = prewarm;
    /* the other sets (the drag stretch's 222 … 256) are loaded one per idle slot after the first prewarm, so no gesture frame pays a set's upload + inner-shadow pass
       (each ~1–2 ms on the Mac, more on the phone; the lift itself never needs them — it rides the 220 set); opts.preloadAll: false leaves them to first use */
    const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 2000 }) : setTimeout(fn, 50));
    const preloadRest = () => { if (opts.preloadAll === false) return; const rest = widths.filter((w) => !sets[w]); if (!rest.length) return; idle(() => { loadSet(rest[0]).then(() => preloadRest()); }); };
    const ready = Promise.all(preload.map((w) => sets[w] && sets[w].ready)).then(() => { warm(); preloadRest(); return true; });
    const setBackdrop = (b) => { if (b.region) region = b.region; if (b.ink) opts.ink = b.ink; opts.backdrop = (x, which, info) => { if (which === "page" && b.page) b.page(x, info); if (which === "labels" && b.labels) b.labels(x, info); };
      if (b.sync !== false && !stats.frames) { redrawNow(); if (sets[preload[0]] && sets[preload[0]].loaded) warm(); } else redrawBackdrop(b); };   /* before any frame (idle setup): now; later: deferred, then warmed */
    const redrawAndWarm = (o) => redrawBackdrop(o);
    const draw = (d) => {   /* the ui form: the canvas sits at (lensX − AM, lensY − AM); its size is fixed (the largest wrapper), the frame draws the wrapper into its top-left */
      setState({ cx: d.lensX + d.w / 2, cy: d.lensY + d.h / 2, w: d.w, h: d.h, lift: d.p, pd: d.pd, wh: d.wh, platter: d.platter, canvasOrigin: { x: d.lensX - AM, y: d.lensY - AM } });
      return stats.gpuMs; };
    return { gl, canvas, ready, setState, draw, setBackdrop, redrawBackdrop: redrawAndWarm, redrawNow, prewarm, prepareLabels, useLabels, hasLabels, backdropCanvas: () => composite, stats, sets, loadSet, get region() { return region; }, destroy: () => { gl.getExtension("WEBGL_lose_context")?.loseContext(); scratch.remove(); } };   // the backdrop scratch canvases go with the lens (界面-串2 ②: every tab-set change left one 1392×330 pair behind)
  };
  /* the sets from the page's inline <svg>: #<prefix>-lens-f-bg-<w> (href, data-s), -lab-, -ab- (data-s) — the same files the SVG filters use; h from the map's pixel height / 2 is not known here: pass heights (view.js's series table) or let the page's set table carry them */
  const setsFromFilters = (prefix, heights) => { const out = {}; for (const f of document.querySelectorAll(`filter[id^="${prefix}-lens-f-bg-"]`)) { const w = parseInt(f.id.slice(`${prefix}-lens-f-bg-`.length), 10); if (!(w > 0)) continue;
      const href = (el) => el && (el.dataset.hrefOrig || el.getAttribute("href") || el.getAttributeNS("http://www.w3.org/1999/xlink", "href"));   /* data-href-orig: the file behind lens-engine-fix.js's blob: copy (the GPU path samples the plain map) */
      const bg = href(f.querySelector("feImage")), lab = href(document.querySelector(`#${prefix}-lens-f-lab-${w} feImage`)), fab = document.querySelector(`#${prefix}-lens-f-ab-${w}`), ab = href(fab && fab.querySelector("feImage"));
      if (!bg || !lab || !ab) continue; const S0 = parseFloat(f.dataset.s0 || f.dataset.s) || 40; const Sab = fab ? parseFloat(fab.dataset.s) || 12 : 12;
      out[w] = { bg, lab, ab, S: S0, Sab, h: heights && heights[w] ? heights[w] : null }; } return out; };
  /* R96 (页面 bug): a lens canvas paints past the viewport — the tab bar's canvas is nav ± 24 (its right edge 452 on a 440 screen with five tabs, its bottom 968),
     the segment's canvas is scaled by the flex transform (× 1.1 about the lens centre) — and a mobile browser lets overflowing content widen the layout viewport
     (界面's frame log: innerWidth 440 → 455 for a few frames, the fixed tab bar 3 px lower = the user's bug ②) or pan the page sideways. clipCanvas wraps the
     canvas in an overflow-hidden box (.lens-clip) that is the canvas's nominal box clamped to [0, innerWidth] (and to [0, innerHeight] when `y`), and gives the
     canvas explicit pixel size / offsets inside it, so nothing the lens draws can extend the document; the drawing itself is unchanged (the canvas keeps its
     size and mapping, the wrapper only clips). Call it again after a layout change (a resize, the bar recentred) — it re-measures the parent. */
  const clipCanvas = (canvas, ax = {}) => { if (!canvas || !canvas.parentElement) return null; let w = canvas.parentElement; const fresh = !w.classList.contains("lens-clip");
    if (fresh) { const nom = { l: canvas.offsetLeft, t: canvas.offsetTop, w: canvas.offsetWidth, h: canvas.offsetHeight }, cs = getComputedStyle(canvas); w = document.createElement("div"); w.className = "lens-clip"; w.dataset.nom = JSON.stringify(nom);
      w.style.cssText = `position:absolute;overflow:hidden;pointer-events:none;z-index:${cs.zIndex === "auto" ? 0 : cs.zIndex}`; canvas.replaceWith(w); w.appendChild(canvas);
      canvas.style.position = "absolute"; canvas.style.width = nom.w + "px"; canvas.style.height = nom.h + "px"; canvas.style.zIndex = "0"; }
    const nom = JSON.parse(w.dataset.nom), parent = w.offsetParent || w.parentElement, pr = parent.getBoundingClientRect();
    const pad = ax.pad || 0;   // room for a transform that grows the canvas (the segment's flex scale): the box before the clamp is the nominal box ± pad in x
    const L = pr.left + nom.l, T = pr.top + nom.t, R = L + nom.w, B = T + nom.h, cl = Math.max(0, L - pad), cr = Math.min(innerWidth, R + pad), ct = ax.y ? Math.max(0, T) : T, cb = ax.y ? Math.min(innerHeight, B) : B;
    w.style.left = (cl - pr.left) + "px"; w.style.top = (ct - pr.top) + "px"; w.style.width = Math.max(0, cr - cl) + "px"; w.style.height = Math.max(0, cb - ct) + "px";
    canvas.style.left = (L - cl) + "px"; canvas.style.top = (T - ct) + "px"; w.dataset.clip = `${Math.round(cl)},${Math.round(ct)},${Math.round(cr)},${Math.round(cb)}`; return w; };
  window.LensWebGL = { create, setsFromFilters, clipCanvas, VS, FS1, FS2, FS_ISH, COMMON };
})();
