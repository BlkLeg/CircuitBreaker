// apps/agent/internal/enroll/arch.go
package enroll

import "runtime"

func goArch() string { return runtime.GOARCH }
