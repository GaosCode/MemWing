class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://github.com/GaosCode/MemWing"
  url "https://github.com/GaosCode/MemWing/releases/download/v0.1.2/memwing-0.1.2.tar.gz"
  sha256 "0dbfd9cff1c5a6a40d22a1c2e5975f96b4ef80c4cc92fa7784a0e3933b825b86"
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
