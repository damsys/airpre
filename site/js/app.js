(() => {
  const config = window.AIRPRE_CONFIG || {};
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);

  const state = {
    catalog: null,
    areaId: null,
    data: null,
    range: "24h",
    series: "pressure",
    points: [],
    alertIntervals: [],
  };

  const els = {
    areaTitle: document.getElementById("area-title"),
    areaLede: document.getElementById("area-lede"),
    areaChips: document.getElementById("area-chips"),
    current: document.getElementById("current-value"),
    observedAt: document.getElementById("observed-at"),
    trend: document.getElementById("trend"),
    seriesLabel: document.getElementById("series-label"),
    delta3h: document.getElementById("delta-3h"),
    rangeMin: document.getElementById("range-min"),
    rangeMax: document.getElementById("range-max"),
    status: document.getElementById("status"),
    chart: document.getElementById("chart"),
    tooltip: document.getElementById("tooltip"),
    chartHint: document.getElementById("chart-hint"),
    stationNote: document.getElementById("station-note"),
    sourceLink: document.getElementById("source-link"),
  };

  function changeAlertConfig() {
    const alert = config.changeAlert || {};
    const windowHours = Number(alert.windowHours);
    const thresholdHpa = Number(alert.thresholdHpa);
    return {
      windowHours: Number.isFinite(windowHours) && windowHours > 0 ? windowHours : 2,
      thresholdHpa: Number.isFinite(thresholdHpa) && thresholdHpa > 0 ? thresholdHpa : 1.0,
    };
  }

  const rangeMs = {
    "6h": 6 * 60 * 60 * 1000,
    "24h": 24 * 60 * 60 * 1000,
    "3d": 3 * 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
  };

  function isLocal() {
    return localHosts.has(location.hostname);
  }

  function catalogUrl() {
    return isLocal() ? config.localCatalogUrl : config.remoteCatalogUrl;
  }

  function areaDataUrl(areaId) {
    const template = isLocal() ? config.localAreaUrlTemplate : config.remoteAreaUrlTemplate;
    return template.replace("{id}", encodeURIComponent(areaId));
  }

  function showStatus(message) {
    els.status.hidden = !message;
    els.status.textContent = message || "";
  }

  function formatNumber(value, digits = 1) {
    return Number(value).toFixed(digits);
  }

  function formatDateTime(iso) {
    const date = new Date(iso);
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function formatAxisTime(iso, spanMs) {
    const date = new Date(iso);
    const options =
      spanMs > 36 * 60 * 60 * 1000
        ? { month: "numeric", day: "numeric", hour: "2-digit" }
        : { hour: "2-digit", minute: "2-digit" };
    return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", ...options }).format(date);
  }

  function signed(value) {
    const prefix = value > 0 ? "+" : "";
    return `${prefix}${formatNumber(value)}`;
  }

  function seriesLabel(key) {
    return key === "pressure" ? "現地気圧" : "海面更正気圧";
  }

  function currentArea() {
    return state.catalog?.areas?.find((area) => area.id === state.areaId) || null;
  }

  function pickAreaId(catalog) {
    const requested = new URLSearchParams(location.search).get("area");
    if (requested && catalog.areas.some((area) => area.id === requested)) {
      return requested;
    }
    return catalog.areas.find((area) => area.hasData)?.id || catalog.areas[0]?.id || null;
  }

  function setAreaInUrl(areaId) {
    const url = new URL(location.href);
    url.searchParams.set("area", areaId);
    history.replaceState(null, "", url);
  }

  function visiblePoints() {
    const observations = state.data?.observations || [];
    const filtered = observations
      .map((item) => {
        const value = item[state.series];
        if (value == null) {
          return null;
        }
        return { time: item.time, ms: Date.parse(item.time), value };
      })
      .filter(Boolean);
    if (!filtered.length || state.range === "all") {
      return filtered;
    }
    const newest = filtered[filtered.length - 1].ms;
    const cutoff = newest - rangeMs[state.range];
    return filtered.filter((point) => point.ms >= cutoff);
  }

  function findAround(points, targetMs, windowMs) {
    let best = null;
    for (const point of points) {
      const delta = Math.abs(point.ms - targetMs);
      if (delta <= windowMs && (!best || delta < best.delta)) {
        best = { ...point, delta };
      }
    }
    return best;
  }

  function seriesPoints(observations, seriesKey) {
    return observations
      .map((item) => {
        const value = item[seriesKey];
        if (value == null) {
          return null;
        }
        return { time: item.time, ms: Date.parse(item.time), value };
      })
      .filter(Boolean);
  }

  function findAlertIntervals(points, windowHours, thresholdHpa) {
    if (points.length < 2) {
      return [];
    }
    const windowMs = windowHours * 60 * 60 * 1000;
    const matchSlackMs = 25 * 60 * 1000;
    const flagged = [];
    let lookbackIndex = 0;

    for (let i = 0; i < points.length; i += 1) {
      const point = points[i];
      const targetMs = point.ms - windowMs;
      while (lookbackIndex < i && points[lookbackIndex].ms < targetMs - matchSlackMs) {
        lookbackIndex += 1;
      }
      let baseline = null;
      for (let j = lookbackIndex; j < i; j += 1) {
        const candidate = points[j];
        const skew = Math.abs(candidate.ms - targetMs);
        if (skew > matchSlackMs) {
          if (candidate.ms > targetMs + matchSlackMs) {
            break;
          }
          continue;
        }
        if (!baseline || skew < baseline.skew) {
          baseline = { ...candidate, skew };
        }
      }
      if (!baseline) {
        continue;
      }
      const delta = point.value - baseline.value;
      if (Math.abs(delta) >= thresholdHpa) {
        // lookback 全幅だと広がりすぎるので、後半半分を塗る
        const halfWindowMs = windowMs / 2;
        flagged.push({
          startMs: Math.max(baseline.ms, point.ms - halfWindowMs),
          endMs: point.ms,
          delta,
        });
      }
    }

    if (!flagged.length) {
      return [];
    }

    flagged.sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs);
    const gapMs = 30 * 60 * 1000;
    const intervals = [];
    let current = {
      startMs: flagged[0].startMs,
      endMs: flagged[0].endMs,
      sumDelta: flagged[0].delta,
      count: 1,
    };
    for (let i = 1; i < flagged.length; i += 1) {
      const item = flagged[i];
      if (item.startMs <= current.endMs + gapMs) {
        current.endMs = Math.max(current.endMs, item.endMs);
        current.sumDelta += item.delta;
        current.count += 1;
      } else {
        intervals.push(current);
        current = {
          startMs: item.startMs,
          endMs: item.endMs,
          sumDelta: item.delta,
          count: 1,
        };
      }
    }
    intervals.push(current);
    return intervals.map((interval) => ({
      startMs: interval.startMs,
      endMs: interval.endMs,
      direction: interval.sumDelta / interval.count >= 0 ? "rise" : "fall",
    }));
  }

  function intervalsInView(intervals, minX, maxX) {
    return intervals
      .map((interval) => ({
        ...interval,
        startMs: Math.max(interval.startMs, minX),
        endMs: Math.min(interval.endMs, maxX),
      }))
      .filter((interval) => interval.endMs >= interval.startMs);
  }

  function renderAreaMeta() {
    const area = currentArea();
    const name = state.data?.area?.name || area?.name || "気圧";
    els.areaTitle.textContent = `${name}の気圧`;
    document.title = `${name}の気圧 | airpre`;
    const station = state.data?.station;
    if (station?.office) {
      els.areaLede.textContent = `${station.office}の10分値を、地区ごとに蓄積したアーカイブから表示します。`;
    } else {
      els.areaLede.textContent = "気象庁の観測値を、地区ごとに蓄積したアーカイブから表示します。";
    }
    if (station?.note) {
      els.stationNote.textContent = station.note;
    } else {
      els.stationNote.textContent = "";
    }
    if (station) {
      els.sourceLink.textContent = `気象庁 AMeDAS ${station.name}（${station.id}）`;
    }
    els.areaChips.querySelectorAll("[data-area]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.area === state.areaId);
    });
  }

  function renderAreaChips() {
    els.areaChips.replaceChildren();
    for (const area of state.catalog?.areas || []) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.dataset.area = area.id;
      button.textContent = area.name;
      if (!area.hasData) {
        button.classList.add("is-empty");
        button.title = "この地区の観測はまだありません";
      }
      button.addEventListener("click", () => {
        if (state.areaId === area.id) {
          return;
        }
        setAreaInUrl(area.id);
        loadArea(area.id);
      });
      els.areaChips.append(button);
    }
  }

  function renderStats(points) {
    const latest = points.at(-1);
    els.seriesLabel.textContent = seriesLabel(state.series);
    if (!latest) {
      els.current.textContent = "--.-";
      els.observedAt.textContent = "表示できる観測がありません";
      els.trend.textContent = "—";
      els.delta3h.textContent = "—";
      els.rangeMin.textContent = "—";
      els.rangeMax.textContent = "—";
      return;
    }

    els.current.textContent = formatNumber(latest.value);
    els.observedAt.textContent = `${formatDateTime(latest.time)} 観測`;

    const ago3h = findAround(points, latest.ms - 3 * 60 * 60 * 1000, 20 * 60 * 1000);
    if (ago3h) {
      const delta = latest.value - ago3h.value;
      els.delta3h.textContent = `${signed(delta)} hPa`;
      const trendClass = delta > 0.3 ? "is-rise" : delta < -0.3 ? "is-fall" : "";
      els.trend.className = `trend ${trendClass}`.trim();
      els.trend.textContent =
        delta > 0.3 ? "上昇傾向" : delta < -0.3 ? "下降傾向" : "ほぼ変化なし";
    } else {
      els.delta3h.textContent = "—";
      els.trend.className = "trend";
      els.trend.textContent = "比較できる3時間前のデータがありません";
    }

    const values = points.map((point) => point.value);
    els.rangeMin.textContent = `${formatNumber(Math.min(...values))} hPa`;
    els.rangeMax.textContent = `${formatNumber(Math.max(...values))} hPa`;
  }

  function niceRange(min, max) {
    if (min === max) {
      return { min: min - 1, max: max + 1 };
    }
    const padding = Math.max((max - min) * 0.12, 0.3);
    return { min: min - padding, max: max + padding };
  }

  function drawAlertBands(ctx, intervals, xOf, margin, plotH) {
    const minBandWidth = 3;
    for (const interval of intervals) {
      const x1 = xOf(interval.startMs);
      const x2 = xOf(interval.endMs);
      const width = Math.max(x2 - x1, minBandWidth);
      ctx.fillStyle =
        interval.direction === "rise" ? "rgba(52, 211, 153, 0.16)" : "rgba(251, 113, 133, 0.18)";
      ctx.fillRect(x1, margin.top, width, plotH);
    }
  }

  function updateChartHint(alert, visibleAlerts) {
    if (!els.chartHint) {
      return;
    }
    const base = "指やマウスをグラフに合わせると、その時刻の気圧を表示します。";
    const rule = `急変マーク: ${alert.windowHours}時間で ${alert.thresholdHpa} hPa 以上の変化があった時間帯。`;
    const count =
      visibleAlerts.length > 0
        ? `表示期間に ${visibleAlerts.length} 区間。`
        : "表示期間に該当区間なし。";
    els.chartHint.textContent = `${base} ${rule} ${count}`;
  }

  function drawChart(points, alertIntervals) {
    const canvas = els.chart;
    const tooltip = els.tooltip;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const margin = { top: 16, right: 12, bottom: 28, left: 46 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const alert = changeAlertConfig();

    if (points.length < 2) {
      tooltip.hidden = true;
      ctx.fillStyle = "#93a4bf";
      ctx.font = "13px sans-serif";
      ctx.fillText("グラフを描くには観測が2点以上必要です", margin.left, height / 2);
      canvas.onpointermove = null;
      canvas.onpointerleave = null;
      updateChartHint(alert, []);
      return;
    }

    const minX = points[0].ms;
    const maxX = points[points.length - 1].ms;
    const values = points.map((point) => point.value);
    const { min: minY, max: maxY } = niceRange(Math.min(...values), Math.max(...values));
    const span = Math.max(maxX - minX, 1);
    const visibleAlerts = intervalsInView(alertIntervals, minX, maxX);

    const xOf = (ms) => margin.left + ((ms - minX) / span) * plotW;
    const yOf = (value) => margin.top + ((maxY - value) / (maxY - minY)) * plotH;

    drawAlertBands(ctx, visibleAlerts, xOf, margin, plotH);

    ctx.strokeStyle = "#2a3b57";
    ctx.fillStyle = "#93a4bf";
    ctx.lineWidth = 1;
    ctx.font = "11px sans-serif";
    const ticks = 4;
    for (let i = 0; i <= ticks; i += 1) {
      const value = minY + ((maxY - minY) * i) / ticks;
      const y = yOf(value);
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(width - margin.right, y);
      ctx.stroke();
      ctx.fillText(formatNumber(value), 8, y + 4);
    }

    const timeTicks = 4;
    for (let i = 0; i <= timeTicks; i += 1) {
      const ms = minX + (span * i) / timeTicks;
      const x = xOf(ms);
      const label = formatAxisTime(new Date(ms).toISOString(), span);
      ctx.fillText(label, Math.min(x - 18, width - 70), height - 8);
    }

    const linePath = () => {
      ctx.beginPath();
      points.forEach((point, index) => {
        const x = xOf(point.ms);
        const y = yOf(point.value);
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
    };

    const fill = ctx.createLinearGradient(0, margin.top, 0, height - margin.bottom);
    fill.addColorStop(0, "rgba(56, 189, 248, 0.28)");
    fill.addColorStop(1, "rgba(56, 189, 248, 0.02)");
    linePath();
    ctx.lineTo(xOf(points[points.length - 1].ms), height - margin.bottom);
    ctx.lineTo(xOf(points[0].ms), height - margin.bottom);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();

    linePath();
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 2.4;
    ctx.stroke();

    const last = points[points.length - 1];
    ctx.beginPath();
    ctx.arc(xOf(last.ms), yOf(last.value), 4.5, 0, Math.PI * 2);
    ctx.fillStyle = "#e8eef8";
    ctx.fill();

    function nearest(clientX) {
      const rect = canvas.getBoundingClientRect();
      const x = clientX - rect.left;
      const ratio = Math.min(1, Math.max(0, (x - margin.left) / plotW));
      const target = minX + ratio * span;
      return points.reduce((best, point) =>
        Math.abs(point.ms - target) < Math.abs(best.ms - target) ? point : best
      );
    }

    function windowDelta(point) {
      const baseline = findAround(points, point.ms - alert.windowHours * 60 * 60 * 1000, 25 * 60 * 1000);
      if (!baseline) {
        return null;
      }
      return point.value - baseline.value;
    }

    function showTooltip(point) {
      const x = xOf(point.ms);
      const y = yOf(point.value);
      const delta = windowDelta(point);
      const deltaText =
        delta == null ? "" : ` / ${alert.windowHours}h ${signed(delta)} hPa`;
      tooltip.hidden = false;
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${y}px`;
      tooltip.textContent = `${formatDateTime(point.time)} / ${formatNumber(point.value)} hPa${deltaText}`;
    }

    canvas.onpointermove = (event) => {
      showTooltip(nearest(event.clientX));
    };
    canvas.onpointerleave = () => {
      tooltip.hidden = true;
    };
    updateChartHint(alert, visibleAlerts);
  }

  function render() {
    renderAreaMeta();
    state.points = visiblePoints();
    const alert = changeAlertConfig();
    const allPoints = seriesPoints(state.data?.observations || [], state.series);
    state.alertIntervals = findAlertIntervals(
      allPoints,
      alert.windowHours,
      alert.thresholdHpa
    );
    renderStats(state.points);
    drawChart(state.points, state.alertIntervals);
  }

  async function loadArea(areaId) {
    state.areaId = areaId;
    state.data = null;
    renderAreaMeta();
    const area = currentArea();
    if (!area?.hasData) {
      showStatus("この地区の観測データはまだありません。");
      render();
      return;
    }
    try {
      const response = await fetch(areaDataUrl(areaId), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      state.data = await response.json();
      showStatus("");
      render();
    } catch (error) {
      console.error(error);
      showStatus("この地区の気圧データを読み込めませんでした。");
      render();
    }
  }

  function bindControls() {
    document.querySelectorAll("[data-range]").forEach((button) => {
      button.addEventListener("click", () => {
        state.range = button.dataset.range;
        document.querySelectorAll("[data-range]").forEach((item) => {
          item.classList.toggle("is-active", item === button);
        });
        render();
      });
    });
    document.querySelectorAll("[data-series]").forEach((button) => {
      button.addEventListener("click", () => {
        state.series = button.dataset.series;
        document.querySelectorAll("[data-series]").forEach((item) => {
          item.classList.toggle("is-active", item === button);
        });
        render();
      });
    });
    window.addEventListener("resize", render);
  }

  async function boot() {
    bindControls();
    try {
      const response = await fetch(catalogUrl(), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      state.catalog = await response.json();
      if (!state.catalog?.areas?.length) {
        showStatus("表示できる地区がまだありません。");
        return;
      }
      renderAreaChips();
      const areaId = pickAreaId(state.catalog);
      setAreaInUrl(areaId);
      await loadArea(areaId);
    } catch (error) {
      console.error(error);
      showStatus(
        "地区カタログを読み込めませんでした。ローカルでは fetch-data のあと docker compose で確認してください。"
      );
    }
  }

  boot();
})();
