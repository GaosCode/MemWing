class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://github.com/GaosCode/MemWing"
  url "https://github.com/GaosCode/MemWing/releases/download/v0.1.4/memwing-0.1.4.tar.gz"
  sha256 "6422c45c75ee0a57fe5ca89d862536e56ce992a0b4a36273a9206cb2fa343185"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    libexec.install Dir["*"]
    python = Formula["python@3.13"].opt_bin/"python3.13"
    artifact_python = (libexec/"PYTHON_MAJOR_MINOR").read.strip
    if artifact_python != "3.13"
      odie "MemWing artifact was built for Python #{artifact_python}, but this formula runs Python 3.13"
    end
    (bin/"memwing").write <<~SH
      #!/bin/sh
      export MEMWING_PYTHON="#{python}"
      exec "#{libexec}/bin/memwing" "$@"
    SH
    chmod 0755, bin/"memwing"
  end

  test do
    assert_match "usage: memwing", shell_output("#{bin}/memwing --help")
  end
end
