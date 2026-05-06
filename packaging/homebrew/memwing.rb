class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://memwing.dev"
  url "https://github.com/memwing/memwing/releases/download/v0.1.0/memwing-0.1.0.tar.gz"
  sha256 :no_check
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    prefix.install Dir["*"]
    python = Formula["python@3.13"].opt_bin/"python3.13"
    inreplace prefix/"bin/memwing", 'exec "$PYTHON_BIN"', "exec \"#{python}\""
    (prefix/"PYTHON_MAJOR_MINOR").write("3.13\n")
    (prefix/"PYTHON_EXECUTABLE").write("python3.13\n")
  end

  test do
    assert_match "usage: memwing", shell_output("#{bin}/memwing --help")
  end
end
