(function () {
  const MIN_VISIBLE = 20;
  const MAX_VISIBLE = 800;
  const ZOOM_STEP = 0.12;

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

  let relayoutTimer = null;
  let suppressRelayoutBridge = false;

  function candleTimes(gd) {
    const trace = gd.data && gd.data[0];
    if (!trace || !trace.x) return [];
    return trace.x.map(function (value) {
      return Date.parse(value);
    });
  }

  function logicalRange(times, startMs, endMs) {
    if (!times.length) return { first: 0, last: 0, count: 0 };
    let first = 0;
    let last = times.length - 1;
    for (let i = 0; i < times.length; i++) {
      if (times[i] >= startMs) {
        first = i;
        break;
      }
    }
    for (let i = times.length - 1; i >= 0; i--) {
      if (times[i] <= endMs) {
        last = i;
        break;
      }
    }
    if (first > last) {
      const swap = first;
      first = last;
      last = swap;
    }
    return { first: first, last: last, count: last - first + 1 };
  }

  function isoRange(times, first, last) {
    return [new Date(times[first]).toISOString(), new Date(times[last]).toISOString()];
  }

  function priceRange(gd, first, last) {
    const candle = gd.data[0];
    if (!candle) return null;
    let low = Infinity;
    let high = -Infinity;
    for (let i = first; i <= last; i++) {
      low = Math.min(low, candle.low[i]);
      high = Math.max(high, candle.high[i]);
    }
    for (let t = 1; t < gd.data.length; t++) {
      const trace = gd.data[t];
      if (trace.type === "scatter" && trace.y) {
        trace.y.forEach(function (value) {
          low = Math.min(low, value);
          high = Math.max(high, value);
        });
      }
    }
    if (!Number.isFinite(low) || !Number.isFinite(high)) return null;
    const pad = (high - low) * 0.05 || Math.max(Math.abs(high) * 0.001, 1);
    return [low - pad, high + pad];
  }

  function applyLogicalViewport(gd, first, last, meta) {
    const times = candleTimes(gd);
    if (!times.length) return;
    first = Math.max(0, Math.min(first, times.length - 1));
    last = Math.max(first, Math.min(last, times.length - 1));
    const xRange = isoRange(times, first, last);
    const update = { "xaxis.range": xRange, "xaxis.autorange": false };
    const yRange = priceRange(gd, first, last);
    if (yRange) {
      update["yaxis.range"] = yRange;
      update["yaxis.autorange"] = false;
    }
    suppressRelayoutBridge = true;
    window.Plotly.relayout(gd, update).then(function () {
      setBridge(
        "relayout-bridge",
        JSON.stringify(
          Object.assign(
            {
              "xaxis.range[0]": xRange[0],
              "xaxis.range[1]": xRange[1],
              logical_from: first,
              logical_to: last,
              visible_bars: last - first + 1,
              price_autoscale: true,
            },
            meta || {}
          )
        )
      );
      suppressRelayoutBridge = false;
    });
  }

  function zoomAtCursor(gd, event) {
    const layout = gd._fullLayout;
    const axis = layout.xaxis;
    if (!axis || !axis.range) return;
    const times = candleTimes(gd);
    if (times.length < 2) return;
    const startMs = Date.parse(axis.range[0]);
    const endMs = Date.parse(axis.range[1]);
    const current = logicalRange(times, startMs, endMs);
    const zoomOut = event.deltaY > 0;
    const targetCount = Math.round(current.count * (zoomOut ? 1 + ZOOM_STEP : 1 - ZOOM_STEP));
    const newCount = Math.max(MIN_VISIBLE, Math.min(MAX_VISIBLE, targetCount));
    if (newCount === current.count) return;

    const rect = gd.getBoundingClientRect();
    const px = event.clientX - rect.left - axis._offset;
    const cursorMs = axis.p2d(px);
    let anchor = current.first;
    for (let i = current.first; i <= current.last; i++) {
      if (times[i] <= cursorMs) anchor = i;
    }
    const leftRatio = current.count <= 1 ? 0.5 : (anchor - current.first) / (current.count - 1);
    let newFirst = Math.round(anchor - leftRatio * (newCount - 1));
    let newLast = newFirst + newCount - 1;
    if (newFirst < 0) {
      newLast -= newFirst;
      newFirst = 0;
    }
    if (newLast >= times.length) {
      newFirst -= newLast - (times.length - 1);
      newLast = times.length - 1;
    }
    newFirst = Math.max(0, newFirst);
    newLast = Math.min(times.length - 1, newFirst + newCount - 1);
    applyLogicalViewport(gd, newFirst, newLast, {
      zoom_direction: zoomOut ? "OUT" : "IN",
    });
  }

  function bind() {
    const host = document.getElementById("chart");
    const gd = host && host.querySelector(".js-plotly-plot");
    if (!gd) return;

    if (gd.dataset.plotEventsBound !== "1") {
      gd.dataset.plotEventsBound = "1";
      gd.on("plotly_click", function (event) {
        if (!event || !event.points || !event.points.length) return;
        const point = event.points[0];
        setBridge(
          "manual-click-bridge",
          JSON.stringify({
            x: point.x,
            y: point.y,
            pane_index: 0,
            nonce: Date.now(),
          })
        );
      });
      gd.on("plotly_relayout", function (event) {
        if (!event || event["xaxis.range[0]"] === undefined) return;
        if (suppressRelayoutBridge) return;
        if (relayoutTimer) window.clearTimeout(relayoutTimer);
        relayoutTimer = window.setTimeout(function () {
          setBridge("relayout-bridge", JSON.stringify(event));
        }, 150);
      });
      gd.addEventListener(
        "wheel",
        function (event) {
          if (!gd._fullLayout) return;
          event.preventDefault();
          event.stopPropagation();
          zoomAtCursor(gd, event);
        },
        { passive: false }
      );
    }
  }

  new MutationObserver(bind).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", bind);
})();
