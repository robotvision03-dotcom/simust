/**
 * LearnWebGL-style triangle-mesh volume viewer (TRIANGLES + edges + vertices).
 * Orbit with drag; Ctrl/Cmd+drag a vertex to sculpt. No external deps.
 */
(function (global) {
  function createMeshVolumeViewer(canvas, options) {
    options = options || {};
    var gl = canvas.getContext('webgl', { antialias: true, alpha: false });
    if (!gl) throw new Error('WebGL not available');

    var state = {
      points: [],
      faces: [],
      nTheta: 20,
      nHeight: 10,
      yaw: 0.7,
      pitch: 0.45,
      distance: 180,
      fitDistance: 180,
      minDistance: 8,
      maxDistance: 900,
      draggingOrbit: false,
      draggingVertex: -1,
      lastX: 0,
      lastY: 0,
      selected: -1,
      onVertexDrag: options.onVertexDrag || null,
      onVertexRelease: options.onVertexRelease || null,
      onZoomChange: options.onZoomChange || null,
      faceColor: options.faceColor || [0.22, 0.72, 0.42, 0.92],
      edgeColor: options.edgeColor || [0.95, 0.98, 0.95, 1],
      vertexColor: options.vertexColor || [1, 1, 1, 1],
      selectColor: options.selectColor || [1, 0.8, 0.1, 1],
      bg: options.bg || [0.04, 0.08, 0.14, 1]
    };

    function compile(type, src) {
      var sh = gl.createShader(type);
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(sh));
      }
      return sh;
    }

    var vs = compile(gl.VERTEX_SHADER, [
      'attribute vec3 aPos;',
      'uniform mat4 uMVP;',
      'uniform float uPointSize;',
      'void main(){',
      '  gl_Position = uMVP * vec4(aPos, 1.0);',
      '  gl_PointSize = uPointSize;',
      '}'
    ].join('\n'));
    var fs = compile(gl.FRAGMENT_SHADER, [
      'precision mediump float;',
      'uniform vec4 uColor;',
      'void main(){ gl_FragColor = uColor; }'
    ].join('\n'));
    var prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(prog));
    }
    var aPos = gl.getAttribLocation(prog, 'aPos');
    var uMVP = gl.getUniformLocation(prog, 'uMVP');
    var uColor = gl.getUniformLocation(prog, 'uColor');
    var uPointSize = gl.getUniformLocation(prog, 'uPointSize');
    var buf = gl.createBuffer();

    function mat4Identity() {
      return new Float32Array([
        1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1
      ]);
    }
    function mat4Multiply(a, b) {
      var o = new Float32Array(16);
      for (var c = 0; c < 4; c++) {
        for (var r = 0; r < 4; r++) {
          o[c*4+r] =
            a[0*4+r]*b[c*4+0] + a[1*4+r]*b[c*4+1] +
            a[2*4+r]*b[c*4+2] + a[3*4+r]*b[c*4+3];
        }
      }
      return o;
    }
    function perspective(fovy, aspect, near, far) {
      var f = 1 / Math.tan(fovy / 2);
      var nf = 1 / (near - far);
      var out = new Float32Array(16);
      out[0] = f / aspect; out[5] = f; out[10] = (far + near) * nf;
      out[11] = -1; out[14] = (2 * far * near) * nf;
      return out;
    }
    function lookAt(eye, center, up) {
      var zx = eye[0]-center[0], zy = eye[1]-center[1], zz = eye[2]-center[2];
      var zl = Math.hypot(zx, zy, zz) || 1; zx /= zl; zy /= zl; zz /= zl;
      var xx = up[1]*zz - up[2]*zy;
      var xy = up[2]*zx - up[0]*zz;
      var xz = up[0]*zy - up[1]*zx;
      var xl = Math.hypot(xx, xy, xz) || 1; xx /= xl; xy /= xl; xz /= xl;
      var yx = zy*xz - zz*xy;
      var yy = zz*xx - zx*xz;
      var yz = zx*xy - zy*xx;
      var out = mat4Identity();
      out[0]=xx; out[4]=yx; out[8]=zx;
      out[1]=xy; out[5]=yy; out[9]=zy;
      out[2]=xz; out[6]=yz; out[10]=zz;
      out[12]=-(xx*eye[0]+xy*eye[1]+xz*eye[2]);
      out[13]=-(yx*eye[0]+yy*eye[1]+yz*eye[2]);
      out[14]=-(zx*eye[0]+zy*eye[1]+zz*eye[2]);
      return out;
    }

    function centroid() {
      var pts = state.points;
      if (!pts.length) return [0, 0, 0];
      var sx = 0, sy = 0, sz = 0;
      for (var i = 0; i < pts.length; i++) {
        sx += pts[i][0]; sy += pts[i][1]; sz += (pts[i][2] || 0);
      }
      var n = pts.length;
      return [sx / n, sy / n, sz / n];
    }

    function localPoints() {
      var c = centroid();
      var out = new Float32Array(state.points.length * 3);
      for (var i = 0; i < state.points.length; i++) {
        out[i*3] = state.points[i][0] - c[0];
        out[i*3+1] = state.points[i][1] - c[1];
        out[i*3+2] = (state.points[i][2] || 0) - c[2];
      }
      return out;
    }

    function trianglePositions(local) {
      var faces = state.faces;
      var out = new Float32Array(faces.length * 9);
      var o = 0;
      for (var i = 0; i < faces.length; i++) {
        var f = faces[i];
        for (var k = 0; k < 3; k++) {
          var idx = f[k] * 3;
          out[o++] = local[idx];
          out[o++] = local[idx+1];
          out[o++] = local[idx+2];
        }
      }
      return out;
    }

    function edgePositions(local) {
      var faces = state.faces;
      var seen = {};
      var edges = [];
      function add(a, b) {
        var lo = Math.min(a, b), hi = Math.max(a, b);
        var key = lo + ':' + hi;
        if (seen[key]) return;
        seen[key] = 1;
        edges.push(lo, hi);
      }
      for (var i = 0; i < faces.length; i++) {
        var f = faces[i];
        add(f[0], f[1]); add(f[1], f[2]); add(f[2], f[0]);
      }
      var out = new Float32Array(edges.length * 3);
      var o = 0;
      for (var e = 0; e < edges.length; e++) {
        var idx = edges[e] * 3;
        out[o++] = local[idx];
        out[o++] = local[idx+1];
        out[o++] = local[idx+2];
      }
      return out;
    }

    function mvpMatrix() {
      var w = canvas.clientWidth || canvas.width || 1;
      var h = canvas.clientHeight || canvas.height || 1;
      var aspect = w / Math.max(1, h);
      var proj = perspective(Math.PI / 4, aspect, 0.5, 2000);
      var cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
      var cy = Math.cos(state.yaw), sy = Math.sin(state.yaw);
      var eye = [
        state.distance * cp * sy,
        state.distance * sp,
        state.distance * cp * cy
      ];
      var view = lookAt(eye, [0, 0, 0], [0, 1, 0]);
      return mat4Multiply(proj, view);
    }

    function drawArraysColored(mode, data, color, pointSize) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
      gl.uniform4fv(uColor, color);
      gl.uniform1f(uPointSize, pointSize || 1);
      var count = data.length / 3;
      gl.drawArrays(mode, 0, count);
    }

    function clampDistance(d) {
      return Math.max(state.minDistance, Math.min(state.maxDistance, d));
    }

    function notifyZoom() {
      if (!state.onZoomChange) return;
      var pct = Math.round((state.fitDistance / Math.max(1e-3, state.distance)) * 100);
      state.onZoomChange({
        distance: state.distance,
        fitDistance: state.fitDistance,
        percent: Math.max(10, Math.min(800, pct))
      });
    }

    function fitDistance(local) {
      var maxR = 1;
      for (var i = 0; i < local.length; i += 3) {
        var r = Math.hypot(local[i], local[i+1], local[i+2]);
        if (r > maxR) maxR = r;
      }
      state.fitDistance = Math.max(40, maxR * 2.6);
      state.distance = state.fitDistance;
      state.minDistance = Math.max(4, state.fitDistance * 0.08);
      state.maxDistance = Math.max(200, state.fitDistance * 6);
      notifyZoom();
    }

    function setDistance(d, silent) {
      state.distance = clampDistance(Number(d) || state.distance);
      if (!silent) notifyZoom();
      render();
    }

    function zoomBy(factor) {
      setDistance(state.distance * (Number(factor) || 1));
    }

    function zoomToPercent(percent) {
      var pct = Math.max(10, Math.min(800, Number(percent) || 100));
      setDistance(state.fitDistance * (100 / pct));
    }

    function resetView() {
      state.yaw = 0.7;
      state.pitch = 0.45;
      setDistance(state.fitDistance);
    }

    function render() {
      var dpr = window.devicePixelRatio || 1;
      var w = Math.max(1, Math.floor((canvas.clientWidth || 320) * dpr));
      var h = Math.max(1, Math.floor((canvas.clientHeight || 240) * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(state.bg[0], state.bg[1], state.bg[2], state.bg[3]);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      if (!state.points.length || !state.faces.length) return;

      var local = localPoints();
      var mvp = mvpMatrix();
      gl.useProgram(prog);
      gl.uniformMatrix4fv(uMVP, false, mvp);

      // TRIANGLES faces (LearnWebGL volume surface).
      gl.enable(gl.POLYGON_OFFSET_FILL);
      gl.polygonOffset(1, 1);
      drawArraysColored(gl.TRIANGLES, trianglePositions(local), state.faceColor, 1);
      gl.disable(gl.POLYGON_OFFSET_FILL);

      // Triangle edges.
      gl.lineWidth(1);
      drawArraysColored(gl.LINES, edgePositions(local), state.edgeColor, 1);

      // Vertices.
      drawArraysColored(gl.POINTS, local, state.vertexColor, 8 * dpr);
      if (state.selected >= 0 && state.selected < state.points.length) {
        var sel = new Float32Array([
          local[state.selected*3],
          local[state.selected*3+1],
          local[state.selected*3+2]
        ]);
        drawArraysColored(gl.POINTS, sel, state.selectColor, 14 * dpr);
      }
    }

    function projectToScreen(localIdx) {
      var local = localPoints();
      var mvp = mvpMatrix();
      var x = local[localIdx*3], y = local[localIdx*3+1], z = local[localIdx*3+2];
      var clipX = mvp[0]*x + mvp[4]*y + mvp[8]*z + mvp[12];
      var clipY = mvp[1]*x + mvp[5]*y + mvp[9]*z + mvp[13];
      var clipW = mvp[3]*x + mvp[7]*y + mvp[11]*z + mvp[15];
      if (Math.abs(clipW) < 1e-6) return null;
      var ndcX = clipX / clipW;
      var ndcY = clipY / clipW;
      var rect = canvas.getBoundingClientRect();
      return {
        x: (ndcX * 0.5 + 0.5) * rect.width,
        y: (1 - (ndcY * 0.5 + 0.5)) * rect.height
      };
    }

    function pickVertex(clientX, clientY) {
      var rect = canvas.getBoundingClientRect();
      var px = clientX - rect.left;
      var py = clientY - rect.top;
      var best = -1, bestD = 16;
      for (var i = 0; i < state.points.length; i++) {
        var s = projectToScreen(i);
        if (!s) continue;
        var d = Math.hypot(s.x - px, s.y - py);
        if (d <= bestD) { bestD = d; best = i; }
      }
      return best;
    }

    function screenDeltaToWorld(dx, dy) {
      // Move in the camera plane (approx).
      var scale = state.distance * 0.0035;
      var cy = Math.cos(state.yaw), sy = Math.sin(state.yaw);
      // right = (cy, 0, -sy), up ≈ (0,1,0)
      return [dx * scale * cy, -dy * scale, -dx * scale * sy];
    }

    function onDown(ev) {
      state.lastX = ev.clientX;
      state.lastY = ev.clientY;
      if (ev.ctrlKey || ev.metaKey) {
        var idx = pickVertex(ev.clientX, ev.clientY);
        if (idx >= 0) {
          state.draggingVertex = idx;
          state.selected = idx;
          ev.preventDefault();
          render();
          return;
        }
      }
      state.draggingOrbit = true;
    }
    function onMove(ev) {
      var dx = ev.clientX - state.lastX;
      var dy = ev.clientY - state.lastY;
      state.lastX = ev.clientX;
      state.lastY = ev.clientY;
      if (state.draggingVertex >= 0) {
        var delta = screenDeltaToWorld(dx, dy);
        var p = state.points[state.draggingVertex].slice();
        p[0] += delta[0];
        p[1] += delta[1];
        p[2] = (p[2] || 0) + delta[2];
        state.points[state.draggingVertex] = p;
        if (state.onVertexDrag) state.onVertexDrag(state.draggingVertex, p, state.points);
        render();
        return;
      }
      if (state.draggingOrbit) {
        state.yaw += dx * 0.01;
        state.pitch += dy * 0.01;
        state.pitch = Math.max(-1.2, Math.min(1.2, state.pitch));
        render();
      }
    }
    function onUp() {
      if (state.draggingVertex >= 0) {
        var idx = state.draggingVertex;
        state.draggingVertex = -1;
        if (state.onVertexRelease) state.onVertexRelease(idx, state.points);
      }
      state.draggingOrbit = false;
    }
    function onWheel(ev) {
      zoomBy(ev.deltaY > 0 ? 1.1 : 0.9);
      ev.preventDefault();
    }

    canvas.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    function setMesh(points, faces, meta) {
      state.points = (points || []).map(function (p) {
        return [Number(p[0]), Number(p[1]), Number(p[2] || 0)];
      });
      state.faces = faces || [];
      if (meta) {
        if (meta.nTheta) state.nTheta = meta.nTheta;
        if (meta.nHeight) state.nHeight = meta.nHeight;
      }
      if (!state.faces.length && state.points.length) {
        // Fallback: side quads + caps (same connectivity as simust_cylinder_mesh).
        var nt = state.nTheta, nh = state.nHeight;
        var f = [];
        var z, t, t2, a, b, c, d, base;
        for (z = 0; z < nh - 1; z++) {
          for (t = 0; t < nt; t++) {
            t2 = (t + 1) % nt;
            a = z * nt + t; b = z * nt + t2;
            c = (z + 1) * nt + t2; d = (z + 1) * nt + t;
            f.push([a, b, c], [a, c, d]);
          }
        }
        for (t = 1; t < nt - 1; t++) f.push([0, t + 1, t]);
        base = (nh - 1) * nt;
        for (t = 1; t < nt - 1; t++) f.push([base, base + t, base + t + 1]);
        state.faces = f;
      }
      var local = localPoints();
      fitDistance(local);
      render();
    }

    function destroy() {
      canvas.removeEventListener('mousedown', onDown);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      canvas.removeEventListener('wheel', onWheel);
    }

    return {
      setMesh: setMesh,
      render: render,
      destroy: destroy,
      getPoints: function () { return state.points; },
      setSelected: function (i) { state.selected = i; render(); },
      zoomIn: function () { zoomBy(0.82); },
      zoomOut: function () { zoomBy(1.22); },
      zoomBy: zoomBy,
      zoomToPercent: zoomToPercent,
      setDistance: setDistance,
      resetView: resetView,
      getZoom: function () {
        var pct = Math.round((state.fitDistance / Math.max(1e-3, state.distance)) * 100);
        return {
          distance: state.distance,
          fitDistance: state.fitDistance,
          percent: Math.max(10, Math.min(800, pct))
        };
      }
    };
  }

  global.createMeshVolumeViewer = createMeshVolumeViewer;
})(typeof window !== 'undefined' ? window : this);
