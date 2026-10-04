window.AIRPRE_CONFIG = {
  localCatalogUrl: "/data/areas.json",
  remoteCatalogUrl: "https://raw.githubusercontent.com/damsys/airpre/main/data/areas.json",
  localAreaUrlTemplate: "/data/{id}/latest.json",
  remoteAreaUrlTemplate: "https://raw.githubusercontent.com/damsys/airpre/main/data/{id}/latest.json",
  // 急変マーク: 直近 windowHours の変化量が thresholdHpa 以上なら、
  // 判定時刻から lookback の半分だけ遡った時間帯を塗る。
  changeAlert: {
    windowHours: 2,
    thresholdHpa: 1.0,
  },
};
