type LensFieldOptions = {
  canvas: HTMLCanvasElement
  stage: HTMLElement
  shell: HTMLElement
  lens: HTMLElement
  sharpBrand: HTMLElement
}

type Particle = {
  homeX: number
  homeY: number
  x: number
  y: number
  velocityX: number
  velocityY: number
  phase: number
  size: number
  focused: boolean
}

type TrailPoint = {
  x: number
  y: number
  life: number
  force: number
}

export async function createQuantCodeLensField(options: LensFieldOptions) {
  const context = options.canvas.getContext("2d", { alpha: true })
  if (!context) return () => {}
  const { gsap } = await import("gsap")
  const clampUnit = gsap.utils.clamp(0, 1)
  const clampVelocity = gsap.utils.clamp(-22, 22)

  const field = {
    particles: [] as Particle[],
    trails: [] as TrailPoint[],
    width: 0,
    height: 0,
    lensSize: 0,
    lensX: 0,
    lensY: 0,
    targetX: 0,
    targetY: 0,
    velocityX: 0,
    velocityY: 0,
    pointerX: 0,
    pointerY: 0,
    pointerTime: performance.now(),
    active: false,
    visible: !document.hidden,
    motion: false,
    needsStaticFrame: true,
  }

  const canvasOpacityTo = gsap.quickTo(options.canvas, "opacity", {
    duration: 0.42,
    ease: "power3.out",
    overwrite: "auto",
  })
  const lensOpacityTo = gsap.quickTo(options.lens, "opacity", {
    duration: 0.34,
    ease: "power2.out",
    overwrite: "auto",
  })

  const buildParticles = () => {
    const mask = document.createElement("canvas")
    mask.width = Math.max(1, Math.round(field.width))
    mask.height = Math.max(1, Math.round(field.height))
    const maskContext = mask.getContext("2d", { willReadFrequently: true })
    if (!maskContext) return

    const brandStyle = getComputedStyle(options.sharpBrand)
    const fontSize = Number.parseFloat(brandStyle.fontSize) || Math.min(292, Math.max(154, field.width * 0.17))
    maskContext.fillStyle = "#000"
    maskContext.font = `900 ${fontSize}px "Arial Black", Inter, sans-serif`
    maskContext.textAlign = "center"
    maskContext.textBaseline = "middle"
    maskContext.save()
    maskContext.translate(field.width / 2, field.height * 0.43)
    maskContext.scale(0.95, 1)
    maskContext.fillText("QUANTCODE", 0, 0)
    maskContext.restore()

    const pixels = maskContext.getImageData(0, 0, mask.width, mask.height).data
    const step = field.width > 1180 ? 7 : 6
    const particles: Particle[] = []

    for (let y = step; y < mask.height; y += step) {
      for (let x = step; x < mask.width; x += step) {
        if (pixels[(y * mask.width + x) * 4 + 3] < 120) continue
        if ((x * 17 + y * 13) % 11 > 8) continue
        const phase = ((x * 31 + y * 19) % 628) / 100
        const driftX = Math.sin(phase * 1.7) * 3.5
        const driftY = Math.cos(phase * 1.3) * 2.5
        particles.push({
          homeX: x,
          homeY: y,
          x: x + driftX,
          y: y + driftY,
          velocityX: 0,
          velocityY: 0,
          phase,
          size: 0.65 + ((x * 7 + y * 3) % 8) / 10,
          focused: false,
        })
      }
    }

    field.particles = particles.length > 3600 ? particles.filter((_, index) => index % 2 === 0) : particles
    field.needsStaticFrame = true
  }

  const resize = () => {
    const bounds = options.stage.getBoundingClientRect()
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
    field.width = bounds.width
    field.height = bounds.height
    field.lensSize = options.lens.getBoundingClientRect().width || Math.min(520, Math.max(420, bounds.width * 0.36))
    options.canvas.width = Math.max(1, Math.round(bounds.width * pixelRatio))
    options.canvas.height = Math.max(1, Math.round(bounds.height * pixelRatio))
    options.canvas.style.width = `${bounds.width}px`
    options.canvas.style.height = `${bounds.height}px`
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)

    if (!field.active || !field.lensX) {
      field.lensX = bounds.width * 0.37
      field.lensY = bounds.height * 0.54
      field.targetX = field.lensX
      field.targetY = field.lensY
    }

    buildParticles()
    options.shell.style.setProperty("--qc-lens-x", `${field.lensX}px`)
    options.shell.style.setProperty("--qc-lens-y", `${field.lensY}px`)
  }

  const setPointerTarget = (event: PointerEvent) => {
    if (event.pointerType === "touch") return
    const bounds = options.stage.getBoundingClientRect()
    const radius = Math.min(field.lensSize / 2, bounds.width * 0.24, bounds.height * 0.48)
    const anchorY = bounds.height * 0.54
    const x = gsap.utils.clamp(radius, bounds.width - radius, event.clientX - bounds.left)
    const pointerY = event.clientY - bounds.top
    const y = gsap.utils.clamp(anchorY - 14, anchorY + 14, anchorY + (pointerY - anchorY) * 0.08)
    const now = performance.now()
    const elapsed = Math.max(16, now - field.pointerTime)
    const velocityX = ((x - field.pointerX) / elapsed) * 16
    const velocityY = ((y - field.pointerY) / elapsed) * 16

    field.targetX = x
    field.targetY = y
    field.pointerX = x
    field.pointerY = y
    field.pointerTime = now

    if (Math.hypot(velocityX, velocityY) > 1.8 && now - (field.trails[0]?.life ?? 0) > 18) {
      field.trails.unshift({ x, y, life: now, force: Math.min(1, Math.hypot(velocityX, velocityY) / 18) })
      field.trails.length = Math.min(field.trails.length, 16)
    }
  }

  const activate = (event: PointerEvent) => {
    if (event.pointerType === "touch") return
    field.active = true
    setPointerTarget(event)
    canvasOpacityTo(1)
    lensOpacityTo(1)
  }

  const deactivate = () => {
    field.active = false
    field.targetX = field.width * 0.37
    field.targetY = field.height * 0.54
    canvasOpacityTo(0.82)
    lensOpacityTo(0.9)
  }

  const burst = (event: PointerEvent) => {
    if (event.pointerType === "touch" || !field.motion) return
    const bounds = options.stage.getBoundingClientRect()
    const x = event.clientX - bounds.left
    const y = event.clientY - bounds.top
    const now = performance.now()
    field.trails.unshift(
      ...Array.from({ length: 7 }, (_, index) => ({
        x: x + Math.cos((index / 7) * Math.PI * 2) * 12,
        y: y + Math.sin((index / 7) * Math.PI * 2) * 12,
        life: now - index * 12,
        force: 1,
      })),
    )
    field.trails.length = Math.min(field.trails.length, 20)
  }

  const draw = (time: number) => {
    if (!field.visible || (!field.motion && !field.needsStaticFrame)) return
    field.needsStaticFrame = false
    const acceleration = field.motion ? 0.075 : 1
    const damping = field.motion ? 0.78 : 0
    const nextVelocityX = (field.velocityX + (field.targetX - field.lensX) * acceleration) * damping
    const nextVelocityY = (field.velocityY + (field.targetY - field.lensY) * acceleration) * damping
    field.velocityX = clampVelocity(nextVelocityX)
    field.velocityY = clampVelocity(nextVelocityY)
    field.lensX += field.motion ? field.velocityX : field.targetX - field.lensX
    field.lensY += field.motion ? field.velocityY : field.targetY - field.lensY

    const speed = Math.min(24, Math.hypot(field.velocityX, field.velocityY))
    const direction = Math.atan2(field.velocityY, field.velocityX)
    const radius = field.lensSize / 2
    const now = performance.now()

    options.shell.style.setProperty("--qc-lens-x", `${field.lensX.toFixed(2)}px`)
    options.shell.style.setProperty("--qc-lens-y", `${field.lensY.toFixed(2)}px`)
    options.shell.style.setProperty("--qc-refract-x", `${(field.velocityX * 0.34).toFixed(2)}px`)
    options.shell.style.setProperty("--qc-refract-y", `${(field.velocityY * 0.34).toFixed(2)}px`)
    options.shell.style.setProperty("--qc-lens-scale-x", (1 + Math.abs(field.velocityX) * 0.0018).toFixed(4))
    options.shell.style.setProperty("--qc-lens-scale-y", (1 + Math.abs(field.velocityY) * 0.0018).toFixed(4))
    options.shell.style.setProperty("--qc-lens-rotation", `${(field.velocityX * 0.035).toFixed(2)}deg`)
    options.shell.style.setProperty("--qc-field-energy", (speed / 24).toFixed(3))

    context.clearRect(0, 0, field.width, field.height)
    const focused: Particle[] = []
    const ambient: Particle[] = []

    for (const particle of field.particles) {
      const deltaX = particle.homeX - field.lensX
      const deltaY = particle.homeY - field.lensY
      const distance = Math.max(0.001, Math.hypot(deltaX, deltaY))
      const inside = distance < radius
      const edge = clampUnit(1 - Math.abs(distance - radius) / (radius * 0.32))
      const normalX = deltaX / distance
      const normalY = deltaY / distance
      const focus = inside ? 1 - distance / radius : 0
      const refraction = inside ? Math.sin((distance / radius) * Math.PI) * (5.5 + speed * 0.48) : edge * speed * 0.36
      const drift = field.motion && !inside ? Math.sin(time * 0.0011 + particle.phase) * 1.7 : 0
      const tangentX = -normalY * field.velocityX * focus * 0.2
      const tangentY = normalX * field.velocityY * focus * 0.2
      const targetX = particle.homeX + normalX * refraction + tangentX + drift
      const targetY =
        particle.homeY + normalY * refraction + tangentY + Math.cos(time * 0.0009 + particle.phase) * drift
      const particleSpring = inside ? 0.18 : 0.08
      const particleDamping = inside ? 0.68 : 0.76

      particle.velocityX = (particle.velocityX + (targetX - particle.x) * particleSpring) * particleDamping
      particle.velocityY = (particle.velocityY + (targetY - particle.y) * particleSpring) * particleDamping
      particle.x += particle.velocityX
      particle.y += particle.velocityY
      particle.focused = inside
      ;(inside ? focused : ambient).push(particle)
    }

    context.fillStyle = "#141414"
    context.globalAlpha = 0.42
    context.beginPath()
    for (const particle of ambient) {
      context.rect(particle.x, particle.y, particle.size, particle.size)
    }
    context.fill()

    context.globalAlpha = 0.9
    context.beginPath()
    for (const particle of focused) {
      const radius = particle.size * 0.72
      context.moveTo(particle.x + radius, particle.y)
      context.arc(particle.x, particle.y, radius, 0, Math.PI * 2)
    }
    context.fill()

    field.trails = field.trails.filter((point) => now - point.life < 620)
    context.lineCap = "round"
    for (const point of field.trails) {
      const progress = clampUnit((now - point.life) / 620)
      const offsetX = (point.x - field.lensX) * progress * 0.14
      const offsetY = (point.y - field.lensY) * progress * 0.14
      context.globalAlpha = (1 - progress) * 0.32 * point.force
      context.strokeStyle = "#111"
      context.lineWidth = 0.7
      context.beginPath()
      context.moveTo(point.x - offsetX - 5, point.y - offsetY)
      context.lineTo(point.x - offsetX + 5, point.y - offsetY)
      context.stroke()
    }

    if (speed > 1.5) {
      context.globalAlpha = Math.min(0.3, speed / 70)
      context.strokeStyle = "#111"
      context.lineWidth = 0.75
      context.beginPath()
      context.arc(field.lensX, field.lensY, radius - 7, direction - 0.3, direction + 0.3)
      context.arc(field.lensX, field.lensY, radius + 7, direction + Math.PI - 0.24, direction + Math.PI + 0.24)
      context.stroke()
    }

    context.globalAlpha = 1
  }

  const onVisibilityChange = () => {
    field.visible = !document.hidden
    if (field.visible) field.needsStaticFrame = true
  }

  const media = gsap.matchMedia()
  media.add("(prefers-reduced-motion: no-preference)", () => {
    field.motion = true
    return () => {
      field.motion = false
      field.needsStaticFrame = true
    }
  })

  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(options.stage)
  options.stage.addEventListener("pointerenter", activate)
  options.stage.addEventListener("pointermove", setPointerTarget)
  options.stage.addEventListener("pointerleave", deactivate)
  options.stage.addEventListener("pointerdown", burst)
  document.addEventListener("visibilitychange", onVisibilityChange)
  gsap.ticker.add(draw)
  gsap.ticker.lagSmoothing(500, 33)
  resize()
  draw(gsap.ticker.time)

  return () => {
    resizeObserver.disconnect()
    options.stage.removeEventListener("pointerenter", activate)
    options.stage.removeEventListener("pointermove", setPointerTarget)
    options.stage.removeEventListener("pointerleave", deactivate)
    options.stage.removeEventListener("pointerdown", burst)
    document.removeEventListener("visibilitychange", onVisibilityChange)
    gsap.ticker.remove(draw)
    gsap.killTweensOf([options.canvas, options.lens])
    media.revert()
  }
}
