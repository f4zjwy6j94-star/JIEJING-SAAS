"use strict";

const BLOCKED_PRODUCTION_IPS = new Set(["43.129.169.223", "43.129.205.244"]);

function normalizedHostname(testBase) {
  return new URL(testBase).hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.+$/, "");
}

function mappedIpv4Address(hostname) {
  const dotted = hostname.match(/^(?:::|(?:0+:){5})ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i);
  if (dotted) {
    const octets = dotted[1].split(".").map(Number);
    return octets.every((octet) => octet >= 0 && octet <= 255) ? octets.join(".") : "";
  }
  const hexadecimal = hostname.match(/^(?:::|(?:0+:){5})ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i);
  if (!hexadecimal) return "";
  const high = Number.parseInt(hexadecimal[1], 16);
  const low = Number.parseInt(hexadecimal[2], 16);
  return [high >> 8, high & 0xff, low >> 8, low & 0xff].join(".");
}

function remoteTestHosts(raw = process.env.JIEJING_REMOTE_TEST_HOSTS || "") {
  return new Set(
    String(raw)
      .split(",")
      .map((host) => host.trim().toLowerCase().replace(/^\[|\]$/g, "").replace(/\.+$/, ""))
      .filter(Boolean),
  );
}

function assertSafeMutationBase(testBase) {
  const hostname = normalizedHostname(testBase);
  const effectiveHostname = mappedIpv4Address(hostname) || hostname;
  const loopback = effectiveHostname === "127.0.0.1" || effectiveHostname === "localhost" || effectiveHostname === "::1";
  const productionHost =
    effectiveHostname === "jiejing.shop" ||
    effectiveHostname.endsWith(".jiejing.shop") ||
    BLOCKED_PRODUCTION_IPS.has(effectiveHostname);
  if (productionHost) {
    throw new Error(`browser mutation smoke refuses production host: ${effectiveHostname}`);
  }
  if (loopback) return effectiveHostname;
  const explicitOptIn = process.env.JIEJING_ALLOW_REMOTE_TEST_MUTATION === "true";
  const allowlisted = remoteTestHosts().has(effectiveHostname);
  if (!explicitOptIn || !allowlisted) {
    throw new Error(`remote mutation smoke requires explicit opt-in and exact hostname allowlist: ${effectiveHostname}`);
  }
  return effectiveHostname;
}

module.exports = { assertSafeMutationBase, mappedIpv4Address, normalizedHostname, remoteTestHosts };
