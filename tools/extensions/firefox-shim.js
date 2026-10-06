(function () {
  var tag = function (x) {
    return x != null ? Object.prototype.toString.call(x) : "";
  };

  var patchHasInstance = function (Ctor, tagName) {
    if (typeof Ctor !== "function") return;
    try {
      Object.defineProperty(Ctor, Symbol.hasInstance, {
        value: function (x) {
          return tag(x) === tagName;
        },
        writable: true,
        configurable: true
      });
    } catch (_) {}
  };

  patchHasInstance(typeof ArrayBuffer !== "undefined" ? ArrayBuffer : null, "[object ArrayBuffer]");
  patchHasInstance(typeof Blob !== "undefined" ? Blob : null, "[object Blob]");

  if (typeof chrome === "undefined" || !chrome.runtime) return;

  var safeClone = function (v) {
    if (v === null || typeof v !== "object") return v;
    try {
      return JSON.parse(JSON.stringify(v));
    } catch (_) {
      return v;
    }
  };

  if (chrome.runtime.sendMessage) {
    var origRuntimeSend = chrome.runtime.sendMessage.bind(chrome.runtime);
    chrome.runtime.sendMessage = function () {
      var args = Array.prototype.slice.call(arguments);
      if (args.length > 0) {
        if (typeof args[0] === "string" && args.length > 1) {
          args[1] = safeClone(args[1]);
        } else if (typeof args[0] === "object" && args[0] !== null) {
          args[0] = safeClone(args[0]);
        }
      }
      return origRuntimeSend.apply(null, args);
    };
  }

  if (chrome.tabs && chrome.tabs.sendMessage) {
    var origTabsSend = chrome.tabs.sendMessage.bind(chrome.tabs);
    chrome.tabs.sendMessage = function (tabId, message) {
      var rest = Array.prototype.slice.call(arguments, 2);
      return origTabsSend.apply(
        null,
        [tabId, safeClone(message)].concat(rest)
      );
    };
  }

  if (chrome.storage && chrome.storage.local) {
    if (chrome.storage.local.set) {
      var origLocalSet = chrome.storage.local.set.bind(chrome.storage.local);
      chrome.storage.local.set = function (items, callback) {
        return origLocalSet(safeClone(items), callback);
      };
    }
  }

  if (chrome.storage && chrome.storage.sync) {
    if (chrome.storage.sync.set) {
      var origSyncSet = chrome.storage.sync.set.bind(chrome.storage.sync);
      chrome.storage.sync.set = function (items, callback) {
        return origSyncSet(safeClone(items), callback);
      };
    }
  }

  if (chrome.runtime.connect) {
    var origConnect = chrome.runtime.connect.bind(chrome.runtime);
    chrome.runtime.connect = function () {
      var port = origConnect.apply(null, arguments);
      if (port && typeof port.postMessage === "function") {
        var origPost = port.postMessage.bind(port);
        port.postMessage = function (msg) {
          return origPost(safeClone(msg));
        };
      }
      return port;
    };
  }
})();
