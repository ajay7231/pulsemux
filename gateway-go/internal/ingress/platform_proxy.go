package ingress

import (
	"fmt"
	"net/http"
	"net/http/httputil"
	"net/url"
)

// PlatformProxy forwards HTTP and upgraded WebSocket connections to the shared
// Python runtime. The runtime validates Twilio signatures against PUBLIC_BASE_URL
// and authenticates dashboard sessions; the proxy never handles provider secrets.
// This replaces the standalone mock-worker path when VOICE_RUNTIME_URL is set.
func PlatformProxy(target string) (http.Handler, error) {
	upstream, err := url.Parse(target)
	if err != nil || upstream.Host == "" || (upstream.Scheme != "http" && upstream.Scheme != "https") || upstream.RawQuery != "" || upstream.Fragment != "" {
		return nil, fmt.Errorf("VOICE_RUNTIME_URL must be an HTTP origin")
	}
	proxy := httputil.NewSingleHostReverseProxy(upstream)
	proxy.FlushInterval = -1
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		http.Error(w, "Voice platform is unavailable", http.StatusBadGateway)
	}
	return proxy, nil
}
