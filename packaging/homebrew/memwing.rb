class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://memwing.dev"
  url "https://github.com/GaosCode/MemWing/releases/download/v0.1.0/memwing-0.1.0.tar.gz"
  sha256 "118fb4ef1fb0f026634660364ed3f5480a07cbce288dbda2267e67a5b22d15c9"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    prefix.install Dir["*"]
    python = Formula["python@3.13"].opt_bin/"python3.13"
    artifact_python = (prefix/"PYTHON_MAJOR_MINOR").read.strip
    odie "MemWing artifact was built for Python #{artifact_python}, but this formula runs Python 3.13" unless artifact_python == "3.13"
    inreplace prefix/"bin/memwing", 'exec "$PYTHON_BIN"', "exec \"#{python}\""
  end

  test do
    assert_match "usage: memwing", shell_output("#{bin}/memwing --help")
  end
end
