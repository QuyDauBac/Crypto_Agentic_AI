/* CryptoPilot — auth page interactions
   1) Aurora WebGL mesh-gradient background (real landing-page shader, CSS fallback).
   2) Show/hide password toggles.
   3) Client-side confirm-password match (server cũng validate lại — JS chỉ để UX). */
(function () {
  "use strict";

  // ===== 1) STRIPE-STYLE MESH GRADIENT (WebGL, aurora dark) =====
  function initGL() {
    var canvas = document.getElementById("gradient-canvas");
    if (!canvas) return; // giữ CSS fallback (.aurora-flow)
    var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
    if (!gl) return; // WebGL fail → giữ CSS fallback

    document.documentElement.classList.add("gl-ok");

    var vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0.0,1.0);}";
    var fs = [
      "precision highp float;",
      "uniform vec2 r;",
      "uniform float t;",
      "vec3 cA=vec3(0.913,0.207,0.757);",
      "vec3 cB=vec3(0.545,0.361,0.965);",
      "vec3 cC=vec3(0.133,0.827,0.933);",
      "vec3 cD=vec3(0.388,0.400,0.945);",
      "vec3 bg=vec3(0.0196,0.0196,0.027);",
      "vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}",
      "vec2 mod289(vec2 x){return x-floor(x*(1.0/289.0))*289.0;}",
      "vec3 permute(vec3 x){return mod289(((x*34.0)+1.0)*x);}",
      "float snoise(vec2 v){",
      "  const vec4 C=vec4(0.211324865,0.366025403,-0.577350269,0.024390243);",
      "  vec2 i=floor(v+dot(v,C.yy));",
      "  vec2 x0=v-i+dot(i,C.xx);",
      "  vec2 i1=(x0.x>x0.y)?vec2(1.0,0.0):vec2(0.0,1.0);",
      "  vec4 x12=x0.xyxy+C.xxzz;x12.xy-=i1;",
      "  i=mod289(i);",
      "  vec3 perm=permute(permute(i.y+vec3(0.0,i1.y,1.0))+i.x+vec3(0.0,i1.x,1.0));",
      "  vec3 m=max(0.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.0);",
      "  m=m*m;m=m*m;",
      "  vec3 x=2.0*fract(perm*C.www)-1.0;",
      "  vec3 h=abs(x)-0.5;vec3 ox=floor(x+0.5);vec3 a0=x-ox;",
      "  m*=1.79284291-0.85373472*(a0*a0+h*h);",
      "  vec3 g;",
      "  g.x=a0.x*x0.x+h.x*x0.y;",
      "  g.yz=a0.yz*x12.xz+h.yz*x12.yw;",
      "  return 130.0*dot(m,g);",
      "}",
      "float fbm(vec2 p){",
      "  float s=0.0;float a=0.5;",
      "  for(int i=0;i<4;i++){ s+=a*snoise(p); p*=2.0; a*=0.5; }",
      "  return s;",
      "}",
      "void main(){",
      "  vec2 uv=gl_FragCoord.xy/r.xy;",
      "  vec2 q=uv*1.6;",
      "  float tt=t*0.038;",
      "  vec2 w;",
      "  w.x=fbm(q+vec2(tt,0.0));",
      "  w.y=fbm(q+vec2(5.2,1.3)+vec2(0.0,tt));",
      "  float n=fbm(q+1.8*w+tt*0.5);",
      "  n=n*0.5+0.5;",
      "  vec3 col=mix(cA,cB,smoothstep(0.0,0.5,n));",
      "  col=mix(col,cC,smoothstep(0.35,0.75,n));",
      "  col=mix(col,cD,smoothstep(0.6,1.0,n));",
      "  float darkness=smoothstep(0.2,0.85,n)*0.55+0.12;",
      "  col=mix(bg,col,darkness);",
      "  float vig=smoothstep(1.3,0.3,length(uv-0.5));",
      "  col*=mix(0.7,1.0,vig);",
      "  gl_FragColor=vec4(col,1.0);",
      "}"
    ].join("\n");

    function sh(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        console.error(gl.getShaderInfoLog(s));
        return null;
      }
      return s;
    }

    var prog = gl.createProgram();
    var v = sh(gl.VERTEX_SHADER, vs), f = sh(gl.FRAGMENT_SHADER, fs);
    if (!v || !f) return;
    gl.attachShader(prog, v);
    gl.attachShader(prog, f);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.error("link fail"); return; }
    gl.useProgram(prog);

    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    var pl = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(pl);
    gl.vertexAttribPointer(pl, 2, gl.FLOAT, false, 0, 0);

    var uR = gl.getUniformLocation(prog, "r");
    var uT = gl.getUniformLocation(prog, "t");

    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    function resize() {
      var w = canvas.clientWidth, h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
    }
    window.addEventListener("resize", resize);
    resize();

    canvas.classList.add("loaded");

    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var start = performance.now();
    function frame(now) {
      var t = (now - start) / 1000;
      gl.uniform2f(uR, canvas.width, canvas.height);
      gl.uniform1f(uT, reduce ? 0.0 : t);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      if (!reduce) requestAnimationFrame(frame);
    }
    if (reduce) frame(start); else requestAnimationFrame(frame);
  }

  // ===== 2) SHOW / HIDE PASSWORD =====
  function initPwToggles() {
    var buttons = document.querySelectorAll("[data-toggle-pw]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function () {
        var sel = this.getAttribute("data-toggle-pw");
        var input = document.getElementById(sel);
        if (!input) return;
        input.type = input.type === "password" ? "text" : "password";
      });
    }
  }

  // ===== 3) CONFIRM-PASSWORD MATCH (client-side UX; server validate lại) =====
  function initConfirmPw() {
    var form = document.querySelector("form[data-confirm-pw]");
    if (!form) return;
    var pw = document.getElementById("password");
    var pw2 = document.getElementById("confirm_password");
    var err = document.getElementById("pw-mismatch");
    if (!pw || !pw2) return;

    function validate() {
      var mismatch = pw2.value.length > 0 && pw.value !== pw2.value;
      pw2.setCustomValidity(mismatch ? "Mật khẩu xác nhận không khớp." : "");
      if (err) err.style.display = mismatch ? "flex" : "none";
      return !mismatch;
    }

    pw.addEventListener("input", validate);
    pw2.addEventListener("input", validate);
    form.addEventListener("submit", function (e) {
      if (!validate()) {
        e.preventDefault();
        pw2.focus();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initGL();
    initPwToggles();
    initConfirmPw();
  });
})();
