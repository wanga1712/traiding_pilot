(function () {
  const MIN_VISIBLE_BARS = 60;
  const MAX_VISIBLE_BARS = 800;
  const ZOOM_FACTOR = 0.9;
  const WHEEL_GESTURE_MS = 150;
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
    manualPointSeries: null,
    candles: [],
    payload: null,
    chartInstanceId: null,
    lastMarketDataRevision: null,
    lastAppliedPayloadRaw: null,
    lastSeenPayloadRaw: null,
    initialRangeApplied: false,
    suppressRangeEvent: false,
    relayoutTimer: null,
    wheelAccumulator: 0,
    wheelGestureTimer: null,
    lastWheelAnchor: null,
    rawWheelEventCount: 0,
    appliedZoomGestureCount: 0,
    lastWheelDirection: "—",
    visibleStartIndex: 0,
    visibleEndIndex: 0,
    lockedVisibleCount: 0,
    priceScaleInitialized: false,
    priceYMode: "lock",
    lockedPriceRange: null,
    fixedPriceProvider: null,
    lastAnchorIndex: null,
    latestLogicalRange: null,
    payloadReceivedCount: 0,
    payloadAppliedCount: 0,
    candleSetDataCount: 0,
    panProgrammaticRangeWrites: 0,
    sessionPointCount: 0,
    renderedPointCount: 0,
    lastRenderError: null,
    lastChartError: null,
  };

  function reportChartError(err) {
    const message = err && err.message ? err.message : String(err);
    state.lastChartError = message;
    window.lastChartError = message;
    console.error("CHART ERROR:", err);
    const diag = document.getElementById("chart-error-banner");
    if (diag) diag.textContent = "CHART ERROR: " + message;
  }

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

  function capturePriceRange() {
    if (!state.series || !state.chartContainer) return null;
    const height = state.chartContainer.clientHeight || 0;
    if (height <= 0) return null;
    const minPrice = state.series.coordinateToPrice(height);
    const maxPrice = state.series.coordinateToPrice(0);
    if (minPrice == null || maxPrice == null || !Number.isFinite(minPrice) || !Number.isFinite(maxPrice)) return null;
    return { min: Math.min(minPrice, maxPrice), max: Math.max(minPrice, maxPrice) };
  }

  function applySeriesPriceScaleOptions(autoScale) {
    if (!state.series) return;
    state.series.priceScale().applyOptions({
      autoScale: !!autoScale,
      scaleMargins: { top: 0.1, bottom: 0.1 },
    });
    if (state.chart) {
      state.chart.priceScale("right").applyOptions({ autoScale: !!autoScale });
    }
  }

  function visibleCandlePriceBounds() {
    const start = state.visibleStartIndex;
    const end = state.visibleEndIndex;
    if (!state.candles.length || end < start) return null;
    let minP = Infinity;
    let maxP = -Infinity;
    for (let i = start; i <= end; i++) {
      const c = state.candles[i];
      if (c.low < minP) minP = c.low;
      if (c.high > maxP) maxP = c.high;
    }
    if (!Number.isFinite(minP) || !Number.isFinite(maxP)) return null;
    const span = maxP - minP || Math.max(Math.abs(maxP), 1) * 0.01;
    const pad = span * 0.1;
    return { min: minP - pad, max: maxP + pad };
  }

  function fitWindowY() {
    const bounds = visibleCandlePriceBounds();
    if (!bounds || !state.series) return;
    const provider = function () {
      return { priceRange: { minValue: bounds.min, maxValue: bounds.max } };
    };
    state.fixedPriceProvider = provider;
    state.series.applyOptions({ autoscaleInfoProvider: provider });
    applySeriesPriceScaleOptions(true);
    window.requestAnimationFrame(function () {
      applySeriesPriceScaleOptions(false);
      state.series.applyOptions({ autoscaleInfoProvider: undefined });
      state.fixedPriceProvider = null;
      state.lockedPriceRange = capturePriceRange() || bounds;
      state.priceYMode = "lock";
      state.priceScaleInitialized = true;
    });
  }

  function lockPriceY() {
    applySeriesPriceScaleOptions(false);
    state.priceYMode = "lock";
    state.lockedPriceRange = capturePriceRange();
    state.priceScaleInitialized = true;
  }

  function autoPriceY() {
    state.fixedPriceProvider = null;
    if (state.series) state.series.applyOptions({ autoscaleInfoProvider: undefined });
    applySeriesPriceScaleOptions(true);
    state.priceYMode = "auto";
    state.lockedPriceRange = null;
  }

  function applyPriceScaleMode(mode, initial) {
    if (mode === "auto") {
      autoPriceY();
      return;
    }
    if (mode === "fit" || (initial && !state.priceScaleInitialized)) {
      fitWindowY();
      return;
    }
    lockPriceY();
  }

  function setCandleData(rows) {
    if (!state.series) return;
    state.series.setData(rows || []);
    state.candleSetDataCount += 1;
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
    state.lockedVisibleCount = range.count;
    state.suppressRangeEvent = true;
    state.panProgrammaticRangeWrites += 1;
    state.chart.timeScale().setVisibleLogicalRange({
      from: range.start - 0.5,
      to: range.end + 0.5,
    });
    window.setTimeout(function () {
      state.suppressRangeEvent = false;
      emitViewport(meta || {});
    }, 40);
  }

  function setViewportByCount(newCount, anchorIndex, cursorFraction, meta) {
    newCount = Math.max(MIN_VISIBLE_BARS, Math.min(MAX_VISIBLE_BARS, Math.round(newCount), state.candles.length));
    const barsBefore = Math.round(newCount * cursorFraction);
    const start = anchorIndex - barsBefore;
    const end = start + newCount - 1;
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
            wheel_direction: state.lastWheelDirection,
            raw_wheel_event_count: state.rawWheelEventCount,
            applied_zoom_gesture_count: state.appliedZoomGestureCount,
            payload_received_count: state.payloadReceivedCount,
            payload_applied_count: state.payloadAppliedCount,
            candle_set_data_count: state.candleSetDataCount,
            pan_programmatic_range_writes: state.panProgrammaticRangeWrites,
            min_visible_limit: MIN_VISIBLE_BARS,
            max_visible_limit: MAX_VISIBLE_BARS,
          },
          meta || {}
        )
      )
    );
  }

  function syncFromLogicalPan(logicalRange) {
    if (!logicalRange || state.suppressRangeEvent || !state.candles.length) return;
    const maxIdx = state.candles.length - 1;
    let start = Math.max(0, Math.min(maxIdx, Math.ceil(logicalRange.from)));
    let end = Math.max(start, Math.min(maxIdx, Math.floor(logicalRange.to)));
    const count = end - start + 1;
    state.visibleStartIndex = start;
    state.visibleEndIndex = end;
    state.lockedVisibleCount = count;
    emitViewport({ pan_sync: true });
  }

  function ensureManualPointSeries() {
    if (state.manualPointSeries || !state.chart) return;
    state.manualPointSeries = state.chart.addLineSeries({
      color: "#2962ff",
      lineWidth: 2,
      lineVisible: false,
      pointMarkersVisible: true,
      pointMarkersRadius: 5,
      priceLineVisible: false,
      lastValueVisible: false,
    });
  }

  function renderPoints(points, showGeometry) {
    state.sessionPointCount = (points || []).length;
    state.lastRenderError = null;
    try {
      if (!state.series) {
        state.renderedPointCount = 0;
        return;
      }
      ensureManualPointSeries();
      const sorted = (points || []).slice().sort(function (a, b) {
        return Date.parse(a.timestamp) - Date.parse(b.timestamp);
      });
      const rows = [];
      let lastTime = null;
      for (let i = 0; i < sorted.length; i++) {
        const t = Math.floor(Date.parse(sorted[i].timestamp) / 1000);
        if (!Number.isFinite(t) || (lastTime != null && t <= lastTime)) {
          throw new Error("manual point timestamps must be strictly ascending unique values");
        }
        lastTime = t;
        rows.push({ time: t, value: parseFloat(sorted[i].price) });
      }
      if (state.manualPointSeries) {
        state.manualPointSeries.setData(rows);
        state.manualPointSeries.applyOptions({ lineVisible: !!showGeometry && rows.length > 1 });
        state.manualPointSeries.setMarkers(
          sorted.map(function (p, idx) {
            return {
              time: Math.floor(Date.parse(p.timestamp) / 1000),
              position: "inBar",
              color: "#2962ff",
              shape: "circle",
              text: "P" + (p.point_index != null ? p.point_index : idx),
            };
          })
        );
      }
      state.series.setMarkers([]);
      state.renderedPointCount = rows.length;
    } catch (err) {
      state.lastRenderError = err && err.message ? err.message : String(err);
      state.renderedPointCount = 0;
      reportChartError(err);
    }
  }

  function resolveClickTarget(param) {
    if (!param || !param.point || !state.chart || !state.candles.length) return null;
    const clickPrice = state.series.coordinateToPrice(param.point.y);
    if (clickPrice == null || !Number.isFinite(clickPrice)) return null;
    let barIndex;
    if (param.time != null) {
      const clickedTime = typeof param.time === "number" ? param.time : Math.floor(Date.parse(param.time) / 1000);
      barIndex = state.candles.findIndex(function (c) {
        return c.time === clickedTime;
      });
      if (barIndex < 0) {
        barIndex = Math.max(
          0,
          Math.min(state.candles.length - 1, Math.round(state.chart.timeScale().coordinateToLogical(param.point.x)))
        );
      }
    } else {
      const logical = state.chart.timeScale().coordinateToLogical(param.point.x);
      if (logical == null || !Number.isFinite(logical)) return null;
      barIndex = Math.max(0, Math.min(state.candles.length - 1, Math.round(logical)));
    }
    const candle = state.candles[barIndex];
    const snapMode = (state.payload && state.payload.snap_mode) || "FREE";
    let price = clickPrice;
    if (snapMode === "HIGH") price = candle.high;
    else if (snapMode === "LOW") price = candle.low;
    return {
      time: candle.time,
      timestamp: candle.open_time_utc || isoFromUnix(candle.time),
      price: price,
      barIndex: barIndex,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    };
  }

  function nearestPointIndex(target) {
    const points = (state.payload && state.payload.points) || [];
    if (!points.length) return null;
    let best = null;
    let bestScore = Infinity;
    points.forEach(function (p, idx) {
      const pTime = Math.floor(Date.parse(p.timestamp) / 1000);
      const pIdx = state.candles.findIndex(function (c) {
        return c.time === pTime;
      });
      const barDelta = Math.abs((pIdx >= 0 ? pIdx : target.barIndex) - target.barIndex);
      const priceDelta = Math.abs(parseFloat(p.price) - target.price);
      const score = priceDelta + barDelta * 25;
      if (score < bestScore) {
        bestScore = score;
        best = idx;
      }
    });
    return bestScore <= 120 ? best : null;
  }

  function handleChartClick(param) {
    const target = resolveClickTarget(param);
    if (!target) return;
    const mode = (state.payload && state.payload.interaction_mode) || null;

    if (mode === "DELETE") {
      const pointIndex = nearestPointIndex(target);
      setBridge(
        "manual-click-bridge",
        JSON.stringify({
          action: "delete",
          x: target.timestamp,
          y: target.price,
          bar_index: target.barIndex,
          point_index: pointIndex,
          nonce: Date.now(),
        })
      );
      return;
    }

    if (mode === "MOVE" && state.payload.selected_index == null) {
      const pointIndex = nearestPointIndex(target);
      if (pointIndex != null) {
        setBridge(
          "manual-click-bridge",
          JSON.stringify({
            action: "select",
            point_index: pointIndex,
            nonce: Date.now(),
          })
        );
      }
      return;
    }

    if (mode === "ADD" || mode === "MOVE") {
      setBridge(
        "manual-click-bridge",
        JSON.stringify({
          action: "place",
          x: target.timestamp,
          y: target.price,
          bar_index: target.barIndex,
          nonce: Date.now(),
        })
      );
    }
  }

  function emitCrosshair(param) {
    if (!param || !param.point || !state.candles.length) return;
    const target = resolveClickTarget(param);
    if (!target) return;
    window.lastCrosshair = {
      time: target.timestamp,
      open: target.open,
      high: target.high,
      low: target.low,
      close: target.close,
      cursor_price: target.price,
    };
  }

  function applyWheelGesture() {
    if (!state.chart || !state.candles.length || state.wheelAccumulator === 0) return;
    const zoomIn = state.wheelAccumulator < 0;
    state.wheelAccumulator = 0;
    state.appliedZoomGestureCount += 1;
    state.lastWheelDirection = zoomIn ? "IN" : "OUT";
    const current = visibleCount();
    const newCount = zoomIn ? Math.round(current * ZOOM_FACTOR) : Math.round(current / ZOOM_FACTOR);
    const anchor = state.lastWheelAnchor || {
      anchorIndex: Math.round((state.visibleStartIndex + state.visibleEndIndex) / 2),
      cursorFraction: 0.5,
    };
    setViewportByCount(newCount, anchor.anchorIndex, anchor.cursorFraction, {
      zoom_direction: state.lastWheelDirection,
      anchor_index: anchor.anchorIndex,
      gesture_applied: true,
    });
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
        if (event.deltaY === 0) return;
        state.rawWheelEventCount += 1;
        state.wheelAccumulator += event.deltaY;
        const rect = container.getBoundingClientRect();
        state.lastWheelAnchor = resolveAnchor(event.clientX - rect.left);
        if (state.wheelGestureTimer) window.clearTimeout(state.wheelGestureTimer);
        state.wheelGestureTimer = window.setTimeout(applyWheelGesture, WHEEL_GESTURE_MS);
      },
      { passive: false }
    );
  }

  function applyInitialViewport(payload) {
    const endIdx = payload.visible_end_index != null ? payload.visible_end_index : state.candles.length - 1;
    const startIdx =
      payload.visible_start_index != null
        ? payload.visible_start_index
        : Math.max(0, endIdx - (payload.initial_visible_bars || 480) + 1);
    applyIndexRange(startIdx, endIdx, { initial: true });
    state.initialRangeApplied = true;
  }

  function createChart(container, payload) {
    container.innerHTML = "";
    state.manualPointSeries = null;
    state.priceScaleInitialized = false;
    state.priceYMode = payload.price_y_mode || "lock";
    state.chart = window.LightweightCharts.createChart(container, {
      autoSize: true,
      layout: { background: { color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#242833" }, horzLines: { color: "#242833" } },
      rightPriceScale: { borderColor: "#363a45", autoScale: false },
      timeScale: { borderColor: "#363a45", timeVisible: true, secondsVisible: false, rightOffset: 0 },
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
    setCandleData(state.candles);
    ensureManualPointSeries();

    state.chart.subscribeClick(function (param) {
      handleChartClick(param);
    });
    state.chart.subscribeCrosshairMove(function (param) {
      emitCrosshair(param);
    });
    state.chart.timeScale().subscribeVisibleLogicalRangeChange(function (logicalRange) {
      if (state.suppressRangeEvent || !logicalRange) return;
      state.latestLogicalRange = logicalRange;
      if (state.relayoutTimer) window.clearTimeout(state.relayoutTimer);
      state.relayoutTimer = window.setTimeout(function () {
        syncFromLogicalPan(state.latestLogicalRange);
      }, 150);
    });

    bindWheel(container);

    state.chartInstanceId = payload.chart_instance_id;
    state.lastMarketDataRevision = payload.market_data_revision;
    state.initialRangeApplied = false;
    applyInitialViewport(payload);
    if (payload.fit_window_y) {
      window.requestAnimationFrame(function () {
        fitWindowY();
      });
    } else {
      applyPriceScaleMode(payload.price_y_mode || "lock", true);
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

    const candleDataChanged = payload.market_data_revision !== state.lastMarketDataRevision;
    if (candleDataChanged) {
      const prevLen = state.candles.length;
      const prevStart = state.visibleStartIndex;
      const prevEnd = state.visibleEndIndex;
      state.candles = payload.candles || [];
      setCandleData(state.candles);
      state.lastMarketDataRevision = payload.market_data_revision;
      if (!payload.apply_viewport && prevLen > 0 && state.candles.length > prevLen) {
        const shift = state.candles.length - prevLen;
        applyIndexRange(prevStart + shift, prevEnd + shift, { lazy_load: true });
      }
    }

    if (payload.apply_viewport) {
      if (payload.viewport_count) {
        const anchor = Math.round((state.visibleStartIndex + state.visibleEndIndex) / 2);
        setViewportByCount(payload.viewport_count, anchor, 0.5, { shortcut_target: payload.viewport_count });
      } else if (payload.visible_start_index != null && payload.visible_end_index != null) {
        applyIndexRange(payload.visible_start_index, payload.visible_end_index, {
          shortcut_target: payload.viewport_count,
        });
      }
    }

    if (payload.fit_window_y) {
      fitWindowY();
    } else {
      const nextPriceMode = payload.price_y_mode || "lock";
      if (nextPriceMode !== state.priceYMode) {
        applyPriceScaleMode(nextPriceMode, false);
      }
    }

    renderPoints(payload.points || [], payload.show_geometry);
  }

  function onPayloadBridgeValue() {
    const bridge = document.getElementById("chart-payload-bridge");
    if (!bridge || !bridge.value) return;
    if (bridge.value === state.lastSeenPayloadRaw) return;
    state.lastSeenPayloadRaw = bridge.value;
    state.payloadReceivedCount += 1;
    try {
      applyPayload(JSON.parse(bridge.value));
      state.lastAppliedPayloadRaw = bridge.value;
      state.payloadAppliedCount += 1;
    } catch (err) {
      reportChartError(err);
    }
  }

  function bindPayloadBridge() {
    const bridge = document.getElementById("chart-payload-bridge");
    if (!bridge || bridge.dataset.bound === "1") return;
    bridge.dataset.bound = "1";
    bridge.addEventListener("input", onPayloadBridgeValue);
    bridge.addEventListener("change", onPayloadBridgeValue);
    const observer = new MutationObserver(onPayloadBridgeValue);
    observer.observe(bridge, { attributes: true, attributeFilter: ["value"] });
    if (!window.__lwcPayloadPoll) {
      window.__lwcPayloadPoll = window.setInterval(onPayloadBridgeValue, 200);
    }
    if (bridge.value) onPayloadBridgeValue();
  }

  function waitForLibrary() {
    if (window.LightweightCharts) {
      bindPayloadBridge();
      return;
    }
    window.setTimeout(waitForLibrary, 50);
  }

  new MutationObserver(bindPayloadBridge).observe(document.documentElement, { childList: true, subtree: true });
  window.lockPriceY = lockPriceY;
  window.autoPriceY = autoPriceY;
  window.fitWindowY = fitWindowY;
  window.getPriceScaleDiagnostics = function () {
    const range = capturePriceRange();
    return {
      price_y_mode: state.priceYMode,
      auto_scale: state.priceYMode === "auto",
      price_y_locked: state.priceYMode === "lock",
      locked_range: state.lockedPriceRange,
      visible_range: range,
    };
  };
  window.getManualPointDiagnostics = function () {
    return {
      session_point_count: state.sessionPointCount,
      rendered_point_count: state.renderedPointCount,
      timestamps: ((state.payload && state.payload.points) || []).map(function (p) {
        return p.timestamp;
      }),
      prices: ((state.payload && state.payload.points) || []).map(function (p) {
        return p.price;
      }),
      last_render_error: state.lastRenderError,
    };
  };
  window.getChartStabilityDiagnostics = function () {
    return {
      payload_received_count: state.payloadReceivedCount,
      payload_applied_count: state.payloadAppliedCount,
      candle_set_data_count: state.candleSetDataCount,
      pan_programmatic_range_writes: state.panProgrammaticRangeWrites,
      last_market_data_revision: state.lastMarketDataRevision,
      visible_count: visibleCount(),
      last_chart_error: state.lastChartError,
    };
  };
  window.addEventListener("load", waitForLibrary);
})();
