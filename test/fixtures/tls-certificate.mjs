import {spawnSync} from 'node:child_process';

// 仅在内存生成临时测试证书，不写系统证书库，客户端仍执行证书与主机名校验。
export function certificate() {
  const script = `$ErrorActionPreference='Stop'
    $rsa=[System.Security.Cryptography.RSA]::Create(2048)
    $request=[System.Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=localhost',$rsa,[System.Security.Cryptography.HashAlgorithmName]::SHA256,[System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $san=[System.Security.Cryptography.X509Certificates.SubjectAlternativeNameBuilder]::new()
    $san.AddDnsName('localhost');$san.AddIpAddress([System.Net.IPAddress]::Parse('127.0.0.1'))
    $request.CertificateExtensions.Add($san.Build())
    $cert=$request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-1),[DateTimeOffset]::UtcNow.AddDays(1))
    @{key=$rsa.ExportPkcs8PrivateKeyPem();cert=$cert.ExportCertificatePem()}|ConvertTo-Json -Compress
    $cert.Dispose();$rsa.Dispose()`;
  const child = spawnSync('pwsh', ['-NoProfile', '-NonInteractive', '-Command', script], {encoding: 'utf8', windowsHide: true});
  if (child.status !== 0) throw new Error('test_certificate_generation');
  return JSON.parse(child.stdout);
}
