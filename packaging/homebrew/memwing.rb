class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://memwing.dev"
  url "https://github.com/GaosCode/MemWing/releases/download/v0.1.0/memwing-0.1.0.tar.gz"
  sha256 "9b4f316514d1088bf5d0536614237b89e4bdf1f0647ad961d5a22a83d14f1b2b"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    prefix.install Dir["*"]
    python = Formula["python@3.13"].opt_bin/"python3.13"
    artifact_python = (prefix/"PYTHON_MAJOR_MINOR").read.strip
    if artifact_python != "3.13"
      odie "MemWing artifact was built for Python #{artifact_python}, but this formula runs Python 3.13"
    end
    inreplace prefix/"bin/memwing", 'exec "$PYTHON_BIN"', "exec \"#{python}\""
  end

  test do
    assert_match "usage: memwing", shell_output("#{bin}/memwing --help")
  end
end
