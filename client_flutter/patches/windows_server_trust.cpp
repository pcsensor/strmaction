    // StrmAction: strict private-CA verification through the shared Dart callback.
    wil::com_ptr<ICoreWebView2_14> trustWebView;
    if (SUCCEEDED(webView->QueryInterface(IID_PPV_ARGS(&trustWebView)))) {
      failedLog(trustWebView->add_ServerCertificateErrorDetected(
        Callback<ICoreWebView2ServerCertificateErrorDetectedEventHandler>(
          [this, trustWebView](ICoreWebView2*, ICoreWebView2ServerCertificateErrorDetectedEventArgs* args) -> HRESULT {
            args->put_Action(COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_CANCEL);
            wil::com_ptr<ICoreWebView2Deferral> deferral;
            wil::com_ptr<ICoreWebView2Certificate> certificate;
            wil::unique_cotaskmem_string pem, rawUri;
            wil::com_ptr<IUri> uri;
            if (!channelDelegate || FAILED(args->GetDeferral(&deferral))) return S_OK;
            if (FAILED(args->get_ServerCertificate(&certificate)) || FAILED(certificate->ToPemEncoding(&pem)) ||
                FAILED(args->get_RequestUri(&rawUri)) || FAILED(CreateUri(rawUri.get(), Uri_CREATE_CANONICALIZE, 0, &uri))) {
              deferral->Complete(); return S_OK;
            }
            BSTR rawHost = nullptr;
            DWORD port = 443;
            if (FAILED(uri->GetHost(&rawHost))) { deferral->Complete(); return S_OK; }
            std::string host = wide_to_utf8(rawHost);
            SysFreeString(rawHost);
            uri->GetPort(&port);
            if (host.size() > 2 && host.front() == '[' && host.back() == ']') host = host.substr(1, host.size() - 2);
            auto encoded = wide_to_utf8(pem.get());
            const std::string begin = "-----BEGIN CERTIFICATE-----", end = "-----END CERTIFICATE-----";
            auto first = encoded.find(begin), last = encoded.find(end);
            if (first == std::string::npos || last == std::string::npos || last <= first) { deferral->Complete(); return S_OK; }
            std::string der;
            try {
              auto body = encoded.substr(first + begin.size(), last - first - begin.size());
              body.erase(std::remove_if(body.begin(), body.end(), [](unsigned char value) { return std::isspace(value); }), body.end());
              der = base64_decode(body, false);
            }
            catch (...) { deferral->Complete(); return S_OK; }
            wil::com_ptr<ICoreWebView2ServerCertificateErrorDetectedEventArgs> retained;
            retained.copy_from(args);
            auto finish = [retained, deferral, trustWebView](bool allow) {
              retained->put_Action(allow ? COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_ALWAYS_ALLOW : COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_CANCEL);
              deferral->Complete();
              // Re-evaluate future connections, including CA removal and expiry.
              trustWebView->ClearServerCertificateErrorActions(
                Callback<ICoreWebView2ClearServerCertificateErrorActionsCompletedHandler>([](HRESULT) -> HRESULT { return S_OK; }).Get());
            };
            auto success = [finish](const flutter::EncodableValue* response) {
              bool allow = false;
              if (response) {
                if (const auto* map = std::get_if<flutter::EncodableMap>(response)) {
                  const auto action = map->find(flutter::EncodableValue("action"));
                  if (action != map->end()) {
                    if (const auto* value = std::get_if<int32_t>(&action->second)) allow = *value == 1;
                    if (const auto* value = std::get_if<int64_t>(&action->second)) allow = *value == 1;
                  }
                }
              }
              finish(allow);
            };
            auto error = [finish](const std::string&, const std::string&, const flutter::EncodableValue*) { finish(false); };
            auto missing = [finish]() { finish(false); };
            flutter::EncodableMap protection{
              {flutter::EncodableValue("host"), flutter::EncodableValue(host)},
              {flutter::EncodableValue("port"), flutter::EncodableValue(static_cast<int32_t>(port))},
              {flutter::EncodableValue("protocol"), flutter::EncodableValue("https")},
              {flutter::EncodableValue("sslCertificate"), flutter::EncodableValue(flutter::EncodableMap{
                {flutter::EncodableValue("x509Certificate"), flutter::EncodableValue(std::vector<uint8_t>(der.begin(), der.end()))}
              })}
            };
            channelDelegate->channel->InvokeMethod("onReceivedServerTrustAuthRequest",
              std::make_unique<flutter::EncodableValue>(flutter::EncodableMap{
                {flutter::EncodableValue("protectionSpace"), flutter::EncodableValue(protection)}
              }),
              std::make_unique<flutter::MethodResultFunctions<flutter::EncodableValue>>(success, error, missing));
            return S_OK;
          }).Get(), nullptr));
    }
