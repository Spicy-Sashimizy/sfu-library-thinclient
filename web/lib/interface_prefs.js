
(function () {
  var KEY = "sfu-interface-prefs";

  
  
  
  
  var PREF_DEFAULTS = {
    advancedFiltersOpen: false, 
    savedHistoryNav: true,      
    databasesTab: false,       
    analyticsApp: false,        
    indexManagerApp: false,    
    adminPanels: false,         
    searchQueue: false,         
    searchQueueAuto: true,      
    density: "comfortable"      
  };

  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return Object.assign({}, PREF_DEFAULTS);
      var parsed = JSON.parse(raw);
      
      
      var out = {};
      Object.keys(PREF_DEFAULTS).forEach(function (k) {
        if (parsed && typeof parsed[k] === typeof PREF_DEFAULTS[k]) out[k] = parsed[k];
        else out[k] = PREF_DEFAULTS[k];
      });
      return out;
    } catch (e) { return Object.assign({}, PREF_DEFAULTS); }
  }

  function write(prefs) {
    try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) {}
    
    
    
    try { window.parent.postMessage({ suiteInterfacePrefs: prefs }, "*"); } catch (e) {}
  }

  
  
  function useInterfacePrefs() {
    var React = window.React;
    var s = React.useState(read);
    var prefs = s[0], setPrefs = s[1];
    var setPref = React.useCallback(function (key, value) {
      setPrefs(function (prev) {
        var next = Object.assign({}, prev);
        next[key] = value;
        write(next);
        return next;
      });
    }, []);
    
    React.useEffect(function () {
      var onStorage = function (e) { if (e.key === KEY) setPrefs(read()); };
      window.addEventListener("storage", onStorage);
      return function () { window.removeEventListener("storage", onStorage); };
    }, []);
    return [prefs, setPref];
  }

  
  window.SFUUI = window.SFUUI || {};
  window.SFUUI.INTERFACE_PREF_DEFAULTS = PREF_DEFAULTS;
  window.SFUUI.readInterfacePrefs = read;
  window.SFUUI.writeInterfacePrefs = write;
  window.SFUUI.useInterfacePrefs = useInterfacePrefs;
})();
