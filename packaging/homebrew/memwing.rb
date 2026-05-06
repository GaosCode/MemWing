require "language/python/virtualenv"

class Memwing < Formula
  desc "Local memory control plane for OpenClaw"
  homepage "https://memwing.dev"
  url "https://github.com/memwing/memwing/releases/download/v0.1.0/memwing-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_SHA256"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "usage: memwing", shell_output("#{bin}/memwing --help")
  end
end
