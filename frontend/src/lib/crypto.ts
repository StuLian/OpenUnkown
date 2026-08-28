// 登录/注册密码的 RSA-OAEP 加密，与后端 security/challenge 的私钥解密配对。

function pemToArrayBuffer(pem: string): ArrayBuffer {
  const b64 = pem
    .replace(/-----(BEGIN|END)[^-]+-----/g, "")
    .replace(/\s+/g, "");
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

export async function encryptPassword(
  publicKeyPem: string,
  password: string
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "spki",
    pemToArrayBuffer(publicKeyPem),
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"]
  );
  const data = new TextEncoder().encode(password);
  // RSA-2048 + OAEP-SHA256 的最大明文长度是 190 字节。
  if (data.length > 190) {
    throw new Error("密码过长");
  }
  const ciphertext = await crypto.subtle.encrypt(
    { name: "RSA-OAEP" },
    key,
    data
  );
  return arrayBufferToBase64(ciphertext);
}
