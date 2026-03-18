# Maintainer: BlkLeg <letshost-admin@proton.me>
pkgname=circuit-breaker
pkgver=0.1.0
pkgrel=1
pkgdesc="Circuit Breaker — Homelab topology mapper and network documentation tool"
arch=('x86_64' 'aarch64')
url="https://github.com/BlkLeg/circuitbreaker"
license=('MIT')
depends=('postgresql' 'redis' 'nginx')
optdepends=('nats-server: message bus for internal pub/sub')
install=circuit-breaker.install

source_x86_64=("https://github.com/BlkLeg/circuitbreaker/releases/download/v${pkgver}/circuit-breaker_${pkgver}_amd64.tar.gz")
source_aarch64=("https://github.com/BlkLeg/circuitbreaker/releases/download/v${pkgver}/circuit-breaker_${pkgver}_arm64.tar.gz")

sha256sums_x86_64=('SKIP')
sha256sums_aarch64=('SKIP')

package() {
    local srcname="circuit-breaker_${pkgver}_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
    cd "${srcdir}/${srcname}" 2>/dev/null || cd "${srcdir}"

    install -Dm755 circuit-breaker "${pkgdir}/usr/local/bin/circuit-breaker"

    install -d "${pkgdir}/usr/local/share/circuit-breaker"
    cp -r share/ "${pkgdir}/usr/local/share/circuit-breaker/"

    install -d "${pkgdir}/var/lib/circuit-breaker"
    install -d "${pkgdir}/var/log/circuit-breaker"
    install -d "${pkgdir}/etc/circuit-breaker"
}
