(function () {
  const RIGHT_OFFSET = 3;
  const MIN_VISIBLE_BARS = 30;
  const MAX_VISIBLE_BARS = 500;
  const ZOOM_FACTOR = 0.9;
  const WHEEL_DEBOUNCE_MS = 50;
  const INVARIANT_TOLERANCE = 2;

  function setBridge(id, payload) {
    const bridge = document.getElementById(id);
    if (!bridge) return;
    const previous = bridge.value;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(bridge, payload);
    if (bridge._valueTracker) bridge._valueTracker.setValue(previous);
    bridge.dispatchEvent(new Event("input", { bubbles: true }));
    bridge.dispatchEvent(new Event("change", { bubbles: true }));
  }

  const state = {
    chart: null,
    series: null,
    lineSeries: [],
    candles: [],
    payload: null,
    chartInstanceId: null,
    lastDataRevision: null,
    initialRangeApplied: false,
    suppressRangeEvent: false,
    relayoutTimer: null,
    lastWheelAt: 0,
    lastWheelDeltaRaw: 0,
    lastWheelDirection: "—",
    visibleStartIndex: 0,
    visibleEndIndex: 0,
    lastAnchorIndex: null,
  };

  function isoFromUnix(unix) {
    return new Date(unix * 1000).toISOString();
  }

  function chartWidthPx() {
    if (!state.chartContainer) return 1800;
    return Math.max(320, state.chartContainer.clientWidth || 1800);
  }

  function visibleCount() {
    return state.visibleEndIndex - state.visibleStartIndex + 1;
  }

  function indexForTime(time) {
    if (time == null || !state.candles.length) return 0;
    const target = typeof time === "number" ? time : Math.floor(Date.parse(time) / 1000);
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < state.candles.length; i++) {
      const dist = Math.abs(state.candles[i].time - target);
      if (dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    }
    return best;
  }

  function countBarsBetweenTimes(fromTime, toTime) {
    if (!state.candles.length) return 0;
    const from = typeof fromTime === "number" ? fromTime : Math.floor(Date.parse(fromTime) / 1000);
    const to = typeof toTime === "number" ? toTime : Math.floor(Date.parse(toTime) / 1000);
    const lo = Math.min(from, to);
    const hi = Math.max(from, to);
    let count = 0;
    for (let i = 0; i < state.candles.length; i++) {
      if (state.candles[i].time >= lo && state.candles[i].time <= hi) count++;
    }
    return count;
  }

  function clampIndexRange(start, end, count) {
    const maxIdx = Math.max(0, state.candles.length - 1);
    count = Math.max(MIN_VISIBLE_BARS, Math.min(MAX_VISIBLE_BARS, count, state.candles.length));
    start = Math.max(0, Math.min(start, maxIdx));
    end = start + count - 1;
    if (end > maxIdx) {
      end = maxIdx;
      start = Math.max(0, end - count + 1);
    }
    return { start: start, end: end, count: end - start + 1 };
  }

  function resolveAnchor(localX) {
    const width = chartWidthPx();
    const cursorFraction = Math.max(0, Math.min(1, localX / width));
    let anchorIndex = state.visibleStartIndex + Math.round(visibleCount() * cursorFraction);
    if (state.chart) {
      const logical = state.chart.timeScale().coordinateToLogical(localX);
      if (logical != null && Number.isFinite(logical)) {
        anchorIndex = Math.max(0, Math.min(state.candles.length - 1, Math.round(logical)));
      }
    }
    return { anchorIndex: anchorIndex, cursorFraction: cursorFraction };
  }

  function applyIndexRange(start, end, meta) {
    if (!state.chart || !state.candles.length) return;
    const range = clampIndexRange(start, end, end - start + 1);
    state.visibleStartIndex = range.start;
    state.visibleEndIndex = range.end;
    const fromTime = state.candles[range.start].time;
    const toTime = state.candles[range.end].time;
    state.suppressRangeEvent = true;
    state.chart.timeScale().setVisibleRange({ from: fromTime, to: toTime });
    window.setTimeout(function () {
      state.suppressRangeEvent = false;
      emitViewport(meta || {});
    }, 40);
  }

  function setViewportByCount(newCount, anchorIndex, cursorFraction, meta) {
    newCount = Math.max(MIN_VISIBLE_BARS, Math.min(MAX_VISIBLE_BARS, Math.round(newCount), state.candles.length));
    const barsBefore = Math.round(newCount * cursorFraction);
    let start = anchorIndex - barsBefore;
    let end = start + newCount - 1;
    const clamped = clampIndexRange(start, end, newCount);
    state.lastAnchorIndex = anchorIndex;
    applyIndexRange(clamped.start, clamped.end, meta);
  }

  function emitViewport(meta) {
    if (!state.chart || !state.candles.length) return;
    const start = state.visibleStartIndex;
    const end = state.visibleEndIndex;
    const expected = end - start + 1;
    const fromTime = state.candles[start].time;
    const toTime = state.candles[end].time;
    const counted = countBarsBetweenTimes(fromTime, toTime);
    const invariantOk = Math.abs(counted - expected) <= INVARIANT_TOLERANCE;
    setBridge(
      "relayout-bridge",
      JSON.stringify(
        Object.assign(
          {
            bar_from: start,
            bar_to: end,
            visible_start_index: start,
            visible_end_index: end,
            visible_from_time: state.candles[start].open_time_utc || isoFromUnix(fromTime),
            visible_to_time: state.candles[end].open_time_utc || isoFromUnix(toTime),
            actual_visible_ohlc_bars: expected,
            counted_visible_ohlc_bars: counted,
            viewport_invariant: invariantOk ? "PASS" : "FAIL",
            anchor_index: state.lastAnchorIndex,
            zoom_step_factor: ZOOM_FACTOR,
            wheel_delta_raw: state.lastWheelDeltaRaw,
            wheel_direction: state.lastWheelDirection,
            min_visible_limit: MIN_VISIBLE_BARS,
            max_visible_limit: MAX_VISIBLE_BARS,
          },
          meta || {}
        )
      )
    );
  }

  function syncFromNativePan() {
    if (!state.chart || state.suppressRangeEvent) return;
    const visibleRange = state.chart.timeScale().getVisibleRange();
    if (!visibleRange) return;
    const savedCount = visibleCount();
    const startIdx = indexForTime(visibleRange.from);
    const endIdx = indexForTime(visibleRange.to);
    const resolvedCount = endIdx - startIdx + 1;
    if (Math.abs(resolvedCount - savedCount) <= INVARIANT_TOLERANCE + 1) {
      state.visibleStartIndex = startIdx;
      state.visibleEndIndex = endIdx;
    } else {
      const center = Math.round((startIdx + endIdx) / 2);
      const half = Math.floor(savedCount / 2);
      const clamped = clampIndexRange(center - half, center + half, savedCount);
      state.visibleStartIndex = clamped.start;
      state.visibleEndIndex = clamped.end;
      applyIndexRange(clamped.start, clamped.end, { pan_sync: true });
      return;
    }
    emitViewport({ pan_sync: true });
  }

  function clearLineSeries() {
    state.lineSeries.forEach(function (s) {
      try {
        state.chart.removeSeries(s);
      } catch (e) {}
    });
    state.lineSeries = [];
  }

  function renderPoints(points, showGeometry) {
    clearLineSeries();
    if (!state.series) return;
    if (!points || !points.length) {
      state.series.setMarkers([]);
      return;
    }
    state.series.setMarkers(
      points.map(function (p, idx) {
        return {
          time: Math.floor(Date.parse(p.timestamp) / 1000),
          position: "aboveBar",
          color: "#2962ff",
          shape: "circle",
          text: "P" + (p.point_index != null ? p.point_index : idx),
        };
      })
    );
    if (showGeometry && points.length > 1) {
      const line = state.chart.addLineSeries({
        color: "#2962ff",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        points.map(function (p) {
          return { time: Math.floor(Date.parse(p.timestamp) / 1000), value: parseFloat(p.price) };
        })
      );
      state.lineSeries.push(line);
    }
  }

  function bindWheel(container) {
    if (container.dataset.wheelBound === "1") return;
    container.dataset.wheelBound = "1";
    container.addEventListener(
      "wheel",
      function (event) {
        if (!state.chart || !state.candles.length) return;
        event.preventDefault();
        event.stopPropagation();
        const now = Date.now();
        if (now - state.lastWheelAt < WHEEL_DEBOUNCE_MS) return;
        if (event.deltaY === 0) return;
        state.lastWheelAt = now;
        state.lastWheelDeltaRaw = event.deltaY;
        const zoomIn = event.deltaY < 0;
        state.lastWheelDirection = zoomIn ? "IN" : "OUT";
        const current = visibleCount();
        const newCount = zoomIn ? Math.round(current * ZOOM_FACTOR) : Math.round(current / ZOOM_FACTOR);
        const rect = container.getBoundingClientRect();
        const anchor = resolveAnchor(event.clientX - rect.left);
        setViewportByCount(newCount, anchor.anchorIndex, anchor.cursorFraction, {
          zoom_direction: state.lastWheelDirection,
          anchor_index: anchor.anchorIndex,
        });
      },
      { passive: false }
    );
  }

  function applyInitialViewport(payload) {
    const endIdx = payload.visible_end_index != null ? payload.visible_end_index : state.candles.length - 1;
    const startIdx =
      payload.visible_start_index != null ? payload.visible_start_index : Math.max(0, endIdx - (payload.initial_visible_bars || 120) + 1);
    applyIndexRange(startIdx, endIdx, { initial: true });
    state.initialRangeApplied = true;
  }

  function createChart(container, payload) {
    container.innerHTML = "";
    state.chart = window.LightweightCharts.createChart(container, {
      layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#242833" }, horzLines: { color: "#242833" } },
      rightPriceScale: { borderColor: "#363a45", autoScale: true },
      timeScale: { borderColor: "#363a45", timeVisible: true, secondsVisible: false, rightOffset: RIGHT_OFFSET },
      crosshair: { mode: window.LightweightCharts.CrosshairMode.Normal },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: {
        axisPressedMouseMove: { time: false, price: true },
        axisDoubleClickReset: { time: false, price: true },
        mouseWheel: false,
        pinch: false,
      },
    });
    state.series = state.chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });
    state.chartContainer = container;
    state.candles = payload.candles || [];
    state.series.setData(state.candles);

    state.chart.subscribeClick(function (param) {
      if (!param || !param.point || param.time == null) return;
      const price = state.series.coordinateToPrice(param.point.y);
      setBridge(
        "manual-click-bridge",
        JSON.stringify({ x: isoFromUnix(param.time), y: price, nonce: Date.now() })
      );
    });

    state.chart.timeScale().subscribeVisibleLogicalRangeChange(function () {
      if (state.suppressRangeEvent) return;
      if (state.relayoutTimer) window.clearTimeout(state.relayoutTimer);
      state.relayoutTimer = window.setTimeout(syncFromNativePan, 150);
    });

    bindWheel(container);

    new ResizeObserver(function () {
      if (!state.chart) return;
      const count = visibleCount();
      state.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
      if (count > 0 && state.initialRangeApplied) {
        const anchor = Math.round((state.visibleStartIndex + state.visibleEndIndex) / 2);
        setViewportByCount(count, anchor, 0.5, { resize: true });
      }
    }).observe(container);

    state.chartInstanceId = payload.chart_instance_id;
    state.lastDataRevision = payload.ui_revision;
    state.initialRangeApplied = false;
    applyInitialViewport(payload);
  }

  function updateCandles(payload) {
    const prevLen = state.candles.length;
    const prevStart = state.visibleStartIndex;
    const prevEnd = state.visibleEndIndex;
    state.candles = payload.candles || [];
    state.series.setData(state.candles);
    state.lastDataRevision = payload.ui_revision;

    if (payload.apply_viewport && payload.visible_start_index != null && payload.visible_end_index != null) {
      applyIndexRange(payload.visible_start_index, payload.visible_end_index, { lazy_load: true });
      return;
    }

    if (prevLen > 0 && state.candles.length > prevLen) {
      const shift = state.candles.length - prevLen;
      applyIndexRange(prevStart + shift, prevEnd + shift, { lazy_load: true });
    }
  }

  function applyPayload(payload) {
    if (!payload || !window.LightweightCharts) return;
    const container = document.getElementById("lwc-chart");
    if (!container) return;

    state.payload = payload;
    const needsRecreate = !state.chart || payload.chart_instance_id !== state.chartInstanceId;

    if (needsRecreate) {
      createChart(container, payload);
      renderPoints(payload.points || [], payload.show_geometry);
      return;
    }

    const dataChanged = payload.ui_revision !== state.lastDataRevision || (payload.candles || []).length !== state.candles.length;
    if (dataChanged) {
      updateCandles(payload);
    } else if (payload.apply_viewport) {
      if (payload.viewport_count) {
        const anchor = Math.round((state.visibleStartIndex + state.visibleEndIndex) / 2);
        setViewportByCount(payload.viewport_count, anchor, 0.5, { shortcut_target: payload.viewport_count });
      } else if (payload.visible_start_index != null && payload.visible_end_index != null) {
        applyIndexRange(payload.visible_start_index, payload.visible_end_index, { shortcut_target: payload.viewport_count });
      }
    }

    renderPoints(payload.points || [], payload.show_geometry);
  }

  function bindPayloadBridge() {
    const bridge = document.getElementById("chart-payload-bridge");
    if (!bridge || bridge.dataset.bound === "1") return;
    bridge.dataset.bound = "1";
    bridge.addEventListener("input", function () {
      if (!bridge.value) return;
      try {
        applyPayload(JSON.parse(bridge.value));
      } catch (e) {}
    });
    if (bridge.value) {
      try {
        applyPayload(JSON.parse(bridge.value));
      } catch (e) {}
    }
  }

  function waitForLibrary() {
    if (window.LightweightCharts) {
      bindPayloadBridge();
      return;
    }
    window.setTimeout(waitForLibrary, 50);
  }

  new MutationObserver(bindPayloadBridge).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", waitForLibrary);
})();
