class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://memwing.dev"
  url "https://github.com/GaosCode/MemWing/releases/download/v0.1.1/memwing-0.1.1.tar.gz"
  sha256 "2dccc35f24019daceb0b1d87457a4eb5d4a579ceee6c7487564d24169693a02c"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    libexec.install Dir["*"]
    python = Formula["python@3.13"].opt_bin/"python3.13"
    artifact_python = (libexec/"PYTHON_MAJOR_MINOR").read.strip
    if artifact_python != "3.13"
      odie "MemWing artifact was built for Python #{artifact_python}, but this formula runs Python 3.13"
    end
    inreplace libexec/"bin/memwing", 'exec "$PYTHON_BIN"', "exec \"#{python}\""
    bin.write_exec_script libexec/"bin/memwing"
  end

  test do
    assert_match "usage: memwing", shell_output("#{bin}/memwing --help")
  end
end
