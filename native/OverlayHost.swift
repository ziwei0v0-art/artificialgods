import AppKit
import Foundation

// Decode a crop once into its own compact backing. Scanning RGBA bytes avoids
// millions of temporary NSColor objects and releases the original PNG sheet.
private func compactSceneRaster(_ image:CGImage)->(image:CGImage,alpha:[UInt8])? {
    let width=image.width,height=image.height
    guard let context=CGContext(data:nil,width:width,height:height,bitsPerComponent:8,
        bytesPerRow:width*4,space:CGColorSpace(name:CGColorSpace.sRGB)!,
        bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return nil }
    context.setBlendMode(.copy);context.interpolationQuality = .none
    context.draw(image,in:CGRect(x:0,y:0,width:width,height:height))
    guard let bytes=context.data?.assumingMemoryBound(to:UInt8.self),let decoded=context.makeImage() else { return nil }
    return (decoded,(0..<(width*height)).map { bytes[$0*4+3] })
}

// A01 assets are read-only inputs. Cropping is performed in memory, never on disk.
final class AttendantArtwork {
    static let shared = AttendantArtwork.load()
    private enum Sampling: String, Decodable {
        case nearest, smooth
        var interpolation: NSImageInterpolation { self == .nearest ? .none : .high }
    }
    private struct FrameSpec: Decodable {
        let file: String
        let sourceRect: [Int]?
        let facing: String?
    }
    private struct WalkSpec: Decodable {
        let fps: Double
        let facing: String?
        let frames: [FrameSpec]
    }
    private struct FixedWalkSpec: Decodable {
        let sourceSize: [Int]
        let bodyCutY: Int
        let legStartY: Int
        let legSplitX: Int
        let maxRootStep: Double
        let footLift: Double
    }
    private struct FixedActionsSpec: Decodable {
        let sourceSize: [Int]
        let `catch`: CatchSpec?
        let shared: SharedRigSpec?
        let daily: DailySpec?
        private enum CodingKeys: String, CodingKey { case sourceSize, `catch`, daily }
        init(from decoder:Decoder) throws {
            let values=try decoder.container(keyedBy:CodingKeys.self)
            sourceSize=try values.decode([Int].self,forKey:.sourceSize)
            self.catch=try? values.decode(CatchSpec.self,forKey:.catch)
            // The source sleeve/torso do not depend on a valid net payload.
            shared=try? values.decode(SharedRigSpec.self,forKey:.catch)
            daily=try? values.decode(DailySpec.self,forKey:.daily)
        }
    }
    private struct CatchSpec: Decodable {
        struct Sleeve: Decodable { let mask: [[Double]], pivot: [Double], hand: [Double] }
        struct Underlay: Decodable {
            let file: String, sourceRect: [Int]?, bounds: [Double], bodyArea: [[Double]]
        }
        struct Net: Decodable {
            let file: String, sourceRect: [Int]?, height: Double, grip: [Double], rotation: Double
        }
        let nearSleeve: Sleeve
        let torsoUnderlay: Underlay
        let net: Net
    }
    private struct SharedRigSpec: Decodable {
        let nearSleeve: CatchSpec.Sleeve
        let torsoUnderlay: CatchSpec.Underlay
    }
    private struct DailySpec: Decodable {
        struct Limb: Decodable { let mask:[[Double]],pivot:[Double] }
        struct Prop: Decodable {
            let file:String,sourceRect:[Int]?,height:Double?,grip:[Double]
            let rotation:Double?,minCoreWidth:Double?,groundY:Double?
        }
        struct OptionalProp: Decodable {
            let value:Prop?
            init(from decoder:Decoder) throws { value=try? Prop(from:decoder) }
        }
        let farSleeve:Limb,head:Limb,handCover:[Double],props:[String:OptionalProp]
    }
    private struct Manifest: Decodable {
        let version: Int
        let sampling: Sampling?
        let stand: FrameSpec
        let walk: WalkSpec?
        let fixedWalk: FixedWalkSpec?
        let fixedActions: FixedActionsSpec?
        private enum CodingKeys: String, CodingKey { case version, sampling, stand, walk, fixedWalk, fixedActions }
        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            version = try values.decode(Int.self, forKey: .version)
            sampling = try values.decodeIfPresent(Sampling.self, forKey: .sampling)
            stand = try values.decode(FrameSpec.self, forKey: .stand)
            walk = try values.decodeIfPresent(WalkSpec.self, forKey: .walk)
            // A broken optional articulation must never discard a valid original stand.
            fixedWalk = try? values.decode(FixedWalkSpec.self, forKey: .fixedWalk)
            fixedActions = try? values.decode(FixedActionsSpec.self, forKey: .fixedActions)
        }
    }
    struct Frame {
        let image: NSImage
        let alpha: [UInt8]
        let width: Int
        let height: Int
        let facesLeft: Bool
        let interpolation: NSImageInterpolation

        func contains(_ point: NSPoint, in bounds: NSRect, mirrored: Bool) -> Bool {
            guard bounds.contains(point) else { return false }
            let u = (point.x - bounds.minX) / bounds.width
            let v = (point.y - bounds.minY) / bounds.height
            let rawX = min(width - 1, Int(u * CGFloat(width)))
            let x = mirrored ? width - 1 - rawX : rawX
            let y = min(height - 1, Int(v * CGFloat(height)))
            return alpha[y * width + x] > 16
        }
        func draw(in bounds: NSRect, mirrored: Bool) {
            NSGraphicsContext.saveGraphicsState()
            let transform = NSAffineTransform()
            transform.translateX(by: mirrored ? bounds.maxX : bounds.minX, yBy: bounds.minY)
            transform.scaleX(by: mirrored ? -1 : 1, yBy: 1)
            transform.concat()
            image.draw(in: NSRect(origin: .zero, size: bounds.size), from: .zero,
                       operation: .sourceOver, fraction: 1, respectFlipped: true,
                       hints: [.interpolation: interpolation])
            NSGraphicsContext.restoreGraphicsState()
        }
    }
    struct WalkOffsets: Equatable {
        var leftX: CGFloat = 0, leftLift: CGFloat = 0
        var rightX: CGFloat = 0, rightLift: CGFloat = 0
        static let zero = WalkOffsets()
        func interpolated(to next: WalkOffsets, fraction: CGFloat) -> WalkOffsets {
            let t = min(1, max(0, fraction))
            return WalkOffsets(leftX: leftX + (next.leftX-leftX)*t,
                leftLift: leftLift + (next.leftLift-leftLift)*t,
                rightX: rightX + (next.rightX-rightX)*t,
                rightLift: rightLift + (next.rightLift-rightLift)*t)
        }
    }
    struct Part {
        let frame: Frame
        let bounds: NSRect // Original frame pixels, with a top-left origin.
        var transform: CGAffineTransform = .identity
        var fraction: CGFloat = 1
    }
    struct Rendering {
        let width: Int, height: Int
        let parts: [Part]
    }
    struct CatchPose: Equatable {
        var degrees: CGFloat = 0
        var visibility: CGFloat = 0
        static let zero = CatchPose()
        static func sample(_ elapsed: Double) -> CatchPose {
            guard elapsed.isFinite else { return .zero }
            let t = CGFloat(min(3, max(0, elapsed)))
            func smooth(_ v: CGFloat) -> CGFloat { let x = min(1,max(0,v)); return x*x*(3-2*x) }
            let entry = smooth(t/0.42), exit = 1-smooth((t-2.5)/0.5)
            let reach = smooth((t-0.5)/0.55)*(1-smooth((t-1.25)/0.65))
            return CatchPose(degrees: (-40-35*reach)*entry*exit, visibility: entry*exit)
        }
        func interpolated(to next: CatchPose, fraction: CGFloat) -> CatchPose {
            let t = min(1,max(0,fraction))
            return CatchPose(degrees: degrees+(next.degrees-degrees)*t,
                             visibility: visibility+(next.visibility-visibility)*t)
        }
    }
    // One posed original character and at most one held prop. These are final
    // display parameters, so an interruption never needs to replay old time.
    struct GesturePose: Equatable {
        var nearDegrees:CGFloat=0,farDegrees:CGFloat=0,farScale:CGFloat=1,headDegrees:CGFloat=0
        var prop:String?
        var propScale:CGFloat=0,propRotation:CGFloat=0,propAmount:CGFloat=0
        static let zero=GesturePose()
        var isNeutral:Bool {
            abs(nearDegrees)<0.000001 && abs(farDegrees)<0.000001 && abs(headDegrees)<0.000001
                && abs(farScale-1)<0.000001 && propAmount<0.000001
        }
        static func catching(_ sample:CatchPose)->GesturePose {
            GesturePose(nearDegrees:sample.degrees,prop:sample.visibility>0.000001 ? "net" : nil,
                propScale:sample.visibility,propAmount:sample.visibility)
        }
        func interpolated(to next:GesturePose,fraction:CGFloat)->GesturePose {
            let t=min(1,max(0,fraction))
            func lerp(_ a:CGFloat,_ b:CGFloat)->CGFloat { a+(b-a)*t }
            var result=GesturePose(nearDegrees:lerp(nearDegrees,next.nearDegrees),
                farDegrees:lerp(farDegrees,next.farDegrees),farScale:lerp(farScale,next.farScale),
                headDegrees:lerp(headDegrees,next.headDegrees))
            if prop == next.prop {
                result.prop=prop; result.propScale=lerp(propScale,next.propScale)
                result.propRotation=lerp(propRotation,next.propRotation)
                result.propAmount=lerp(propAmount,next.propAmount)
            } else if prop == nil {
                result.prop=next.prop; result.propScale=next.propScale*t
                result.propRotation=next.propRotation; result.propAmount=next.propAmount*t
            } else if next.prop == nil {
                result.prop=prop; result.propScale=propScale*(1-t)
                result.propRotation=propRotation; result.propAmount=propAmount*(1-t)
            } else if t<0.5 {
                result.prop=prop; result.propScale=propScale*(1-2*t)
                result.propRotation=propRotation; result.propAmount=propAmount*(1-2*t)
            } else {
                result.prop=next.prop; result.propScale=next.propScale*(2*t-1)
                result.propRotation=next.propRotation; result.propAmount=next.propAmount*(2*t-1)
            }
            if result.propAmount<0.000001 { result.prop=nil }
            return result
        }
    }
    // Explicit composition keeps image placement, mirrored input, and bounds on
    // the same affine mapping: apply first, then second.
    static func compose(_ first: CGAffineTransform, _ second: CGAffineTransform) -> CGAffineTransform {
        CGAffineTransform(a: second.a*first.a+second.c*first.b,
            b: second.b*first.a+second.d*first.b, c: second.a*first.c+second.c*first.d,
            d: second.b*first.c+second.d*first.d,
            tx: second.a*first.tx+second.c*first.ty+second.tx,
            ty: second.b*first.tx+second.d*first.ty+second.ty)
    }
    private static func rotation(_ degrees: CGFloat, about p: NSPoint) -> CGAffineTransform {
        let r = degrees * .pi/180, c = cos(r), s = sin(r)
        return CGAffineTransform(a: c,b: s,c: -s,d: c,
                                 tx: p.x-c*p.x+s*p.y,ty: p.y-s*p.x-c*p.y)
    }
    private struct FixedCatch {
        let base: Part, upperBase: Part?, sleeve: Part, underlay: Part, net: Frame
        let pivot: NSPoint, hand: NSPoint, grip: NSPoint
        let netHeight: CGFloat, netRotation: CGFloat
        init?(_ spec: FixedActionsSpec, stand: Frame, fixedWalk: FixedWalk?, directory: URL) {
            guard spec.sourceSize == [stand.width,stand.height] else { return nil }
            guard let s=spec.catch else { return nil }
            let width = CGFloat(stand.width), height = CGFloat(stand.height)
            func point(_ v: [Double], unit: Bool = false) -> NSPoint? {
                guard v.count == 2, v.allSatisfy({ $0.isFinite }), v[0] >= 0, v[1] >= 0,
                      v[0] <= Double(unit ? 1 : width), v[1] <= Double(unit ? 1 : height) else { return nil }
                return NSPoint(x: v[0], y: v[1])
            }
            func polygon(_ values: [[Double]]) -> NSBezierPath? {
                guard (3...64).contains(values.count) else { return nil }
                let points = values.compactMap { point($0) }
                guard points.count == values.count else { return nil }
                let area = zip(points, Array(points.dropFirst())+[points[0]]).reduce(CGFloat(0)) { $0+$1.0.x*$1.1.y-$1.1.x*$1.0.y }
                guard abs(area) > 1 else { return nil }
                let path = NSBezierPath(); path.move(to: points[0]); for p in points.dropFirst() { path.line(to:p) }; path.close()
                return path
            }
            let bounds = s.torsoUnderlay.bounds
            guard let pivot = point(s.nearSleeve.pivot), let hand = point(s.nearSleeve.hand),
                  let grip = point(s.net.grip, unit:true), let sleeveArea = polygon(s.nearSleeve.mask),
                  let bodyArea = polygon(s.torsoUnderlay.bodyArea), bounds.count == 4,
                  bounds.allSatisfy({ $0.isFinite }), bounds[0] >= 0, bounds[1] >= 0,
                  bounds[2] > 0, bounds[3] > 0, bounds[0]+bounds[2] <= Double(width),
                  bounds[1]+bounds[3] <= Double(height), s.net.height.isFinite,
                  s.net.height > 0, s.net.height <= Double(height)*2,
                  s.net.rotation.isFinite, (-180...180).contains(s.net.rotation),
                  let netPixels = AttendantArtwork.read(FrameSpec(file:s.net.file,sourceRect:s.net.sourceRect,facing:nil),in:directory),
                  let underPixels = AttendantArtwork.read(FrameSpec(file:s.torsoUnderlay.file,sourceRect:s.torsoUnderlay.sourceRect,facing:nil),in:directory),
                  let net = netPixels.cropped(to:NSRect(x:0,y:0,width:netPixels.width,height:netPixels.height),facesLeft:stand.facesLeft,interpolation:stand.interpolation),
                  let under = underPixels.cropped(to:NSRect(x:0,y:0,width:underPixels.width,height:underPixels.height),facesLeft:stand.facesLeft,interpolation:stand.interpolation) else { return nil }
            let full = NSRect(x:0,y:0,width:stand.width,height:stand.height)
            let underBounds = NSRect(x:bounds[0],y:bounds[1],width:bounds[2],height:bounds[3])
            guard let base = AttendantArtwork.masked(stand, bounds:full, keeping: { !sleeveArea.contains($0) }),
                  let sleeve = AttendantArtwork.masked(stand, bounds:full, keeping: { sleeveArea.contains($0) }),
                  let underlay = AttendantArtwork.masked(under, bounds:underBounds, keeping: { sleeveArea.contains($0) && bodyArea.contains($0) }) else { return nil }
            self.base=base; self.sleeve=sleeve; self.underlay=underlay; self.net=net
            self.pivot=pivot; self.hand=hand; self.grip=grip
            netHeight=CGFloat(s.net.height); netRotation=CGFloat(s.net.rotation)
            if let fixedWalk {
                guard sleeveArea.bounds.maxY <= fixedWalk.body.bounds.maxY else { return nil }
                upperBase=AttendantArtwork.masked(stand,bounds:full,keeping: { !sleeveArea.contains($0) && $0.y < fixedWalk.body.bounds.maxY })
            } else { upperBase=nil }
        }
        func parts(_ pose: CatchPose, feet: [Part]?) -> [Part] {
            let arm = AttendantArtwork.rotation(pose.degrees,about:pivot)
            let h = netHeight*pose.visibility, w = h*CGFloat(net.width)/CGFloat(net.height)
            let netPart = Part(frame:net,bounds:NSRect(x:hand.x-grip.x*w,y:hand.y-grip.y*h,width:w,height:h),
                transform:AttendantArtwork.compose(AttendantArtwork.rotation(netRotation,about:hand),arm),fraction:pose.visibility)
            let body = feet != nil ? (upperBase ?? base) : base
            return (feet ?? []) + [underlay,body,netPart,Part(frame:sleeve.frame,bounds:sleeve.bounds,transform:arm)]
        }
    }
    private struct LoadedProp {
        let frame:Frame,coreBounds:NSRect
        let height:CGFloat?,grip:NSPoint,rotation:CGFloat,minCoreWidth:CGFloat,groundY:CGFloat?
        func width(height:CGFloat,unitToView:CGFloat)->CGFloat {
            let natural=height*CGFloat(frame.width)/CGFloat(frame.height)
            guard minCoreWidth>0,unitToView>0 else { return natural }
            return max(natural,minCoreWidth/unitToView*CGFloat(frame.width)/coreBounds.width)
        }
    }
    private struct FixedDaily {
        let base:Part,upperBase:Part?,near:Part,far:Part,head:Part,underlay:Part,handCover:Part
        let nearPivot:NSPoint,nearHand:NSPoint,farPivot:NSPoint,headPivot:NSPoint
        let props:[String:LoadedProp]
        init?(_ spec:FixedActionsSpec,stand:Frame,fixedWalk:FixedWalk?,directory:URL) {
            guard spec.sourceSize == [stand.width,stand.height],let shared=spec.shared,let daily=spec.daily else { return nil }
            let w=CGFloat(stand.width),h=CGFloat(stand.height),full=NSRect(x:0,y:0,width:stand.width,height:stand.height)
            func point(_ values:[Double],unit:Bool=false)->NSPoint? {
                guard values.count==2,values.allSatisfy({ $0.isFinite }),values[0]>=0,values[1]>=0,
                      values[0]<=Double(unit ? 1:w),values[1]<=Double(unit ? 1:h) else { return nil }
                return NSPoint(x:values[0],y:values[1])
            }
            func box(_ values:[Double])->NSRect? {
                guard values.count==4,values.allSatisfy({ $0.isFinite }),values[0]>=0,values[1]>=0,
                      values[2]>0,values[3]>0,values[0]+values[2]<=Double(w),values[1]+values[3]<=Double(h) else { return nil }
                return NSRect(x:values[0],y:values[1],width:values[2],height:values[3])
            }
            func polygon(_ values:[[Double]])->NSBezierPath? {
                guard (3...64).contains(values.count) else { return nil }
                let points=values.compactMap { point($0) }
                guard points.count==values.count else { return nil }
                let area=zip(points,Array(points.dropFirst())+[points[0]]).reduce(CGFloat(0)) { $0+$1.0.x*$1.1.y-$1.1.x*$1.0.y }
                guard abs(area)>1 else { return nil }
                let path=NSBezierPath(); path.move(to:points[0]); for p in points.dropFirst() { path.line(to:p) }; path.close()
                return path
            }
            guard let nearArea=polygon(shared.nearSleeve.mask),let farArea=polygon(daily.farSleeve.mask),
                  let headArea=polygon(daily.head.mask),let bodyArea=polygon(shared.torsoUnderlay.bodyArea),
                  let nearPivot=point(shared.nearSleeve.pivot),let nearHand=point(shared.nearSleeve.hand),
                  let farPivot=point(daily.farSleeve.pivot),let headPivot=point(daily.head.pivot),
                  let cover=box(daily.handCover),let underBounds=box(shared.torsoUnderlay.bounds),
                  headArea.bounds.maxY<=min(nearArea.bounds.minY,farArea.bounds.minY),
                  nearArea.bounds.maxX<=farArea.bounds.minX,
                  let underPixels=AttendantArtwork.read(FrameSpec(file:shared.torsoUnderlay.file,
                      sourceRect:shared.torsoUnderlay.sourceRect,facing:nil),in:directory),
                  let under=underPixels.cropped(to:NSRect(x:0,y:0,width:underPixels.width,height:underPixels.height),
                      facesLeft:stand.facesLeft,interpolation:stand.interpolation),
                  let near=AttendantArtwork.masked(stand,bounds:full,keeping:{nearArea.contains($0)}),
                  let far=AttendantArtwork.masked(stand,bounds:full,keeping:{farArea.contains($0)}),
                  let head=AttendantArtwork.masked(stand,bounds:full,keeping:{headArea.contains($0)}),
                  let base=AttendantArtwork.masked(stand,bounds:full,keeping:{!nearArea.contains($0) && !farArea.contains($0) && !headArea.contains($0)}),
                  let underlay=AttendantArtwork.masked(under,bounds:underBounds,keeping:{(nearArea.contains($0) || farArea.contains($0)) && bodyArea.contains($0)}),
                  let handCover=AttendantArtwork.masked(stand,bounds:full,keeping:{cover.contains($0) && nearArea.contains($0)}) else { return nil }
            self.nearPivot=nearPivot; self.nearHand=nearHand; self.farPivot=farPivot; self.headPivot=headPivot
            self.near=near; self.far=far; self.head=head; self.base=base; self.underlay=underlay; self.handCover=handCover
            if let fixedWalk {
                guard max(nearArea.bounds.maxY,farArea.bounds.maxY)<=fixedWalk.body.bounds.maxY else { return nil }
                upperBase=AttendantArtwork.masked(stand,bounds:full,keeping:{!nearArea.contains($0) && !farArea.contains($0) && !headArea.contains($0) && $0.y<fixedWalk.body.bounds.maxY})
            } else { upperBase=nil }
            var loaded:[String:LoadedProp]=[:]
            for name in ["book","broom","fruit","bell","incense","paper"] {
                guard let prop=daily.props[name]?.value,let grip=point(prop.grip,unit:true) else { continue }
                let rotation=prop.rotation ?? 0,minWidth=prop.minCoreWidth ?? 0
                guard rotation.isFinite,(-180...180).contains(rotation),minWidth.isFinite,(0...16).contains(minWidth) else { continue }
                if name=="broom" {
                    guard let ground=prop.groundY,ground.isFinite,ground>0,ground<=Double(h),grip.y<0.95 else { continue }
                } else {
                    guard prop.groundY==nil,let height=prop.height,height.isFinite,height>0,height<=Double(h)*2 else { continue }
                }
                guard let pixels=AttendantArtwork.read(FrameSpec(file:prop.file,sourceRect:prop.sourceRect,facing:nil),in:directory),
                      let frame=pixels.cropped(to:NSRect(x:0,y:0,width:pixels.width,height:pixels.height),facesLeft:stand.facesLeft,
                          interpolation:name=="incense" ? .medium:stand.interpolation),
                      let core=AttendantArtwork.alphaBounds(frame,threshold:16) else { continue }
                loaded[name]=LoadedProp(frame:frame,coreBounds:core,height:prop.height.map { CGFloat($0) },grip:grip,
                    rotation:CGFloat(rotation),minCoreWidth:CGFloat(minWidth),groundY:prop.groundY.map { CGFloat($0) })
            }
            props=loaded
        }
        func canPresent(_ action:String)->Bool {
            if ["practice","rest","response"].contains(action) { return true }
            let names=["read":"book","sweep":"broom","offer":"fruit","bell":"bell","incense":"incense","paper":"paper"]
            return names[action].flatMap { props[$0] } != nil
        }
        func sample(_ action:String,elapsed:Double,duration:Double)->GesturePose {
            guard canPresent(action),elapsed.isFinite,duration.isFinite,duration>0 else { return .zero }
            let t=min(duration,max(0,elapsed)),edge=min(0.55,duration*0.24)
            func smooth(_ v:Double)->CGFloat { let x=min(1,max(0,v)); return CGFloat(x*x*(3-2*x)) }
            let amount=smooth(t/edge)*(1-smooth((t-duration+edge)/edge))
            guard amount>0.000001 else { return .zero }
            var pose=GesturePose(nearDegrees:-40*amount)
            switch action {
            case "read","offer":
                pose.nearDegrees = -43*amount; pose.farDegrees=24*amount; pose.farScale=1-0.2*amount; pose.headDegrees=3*amount
                pose.prop=action=="read" ? "book":"fruit"
            case "practice":
                pose.nearDegrees = -46*amount; pose.farDegrees=28*amount; pose.farScale=1-0.2*amount
                pose.headDegrees=CGFloat(4+3*sin(t * .pi/5))*amount
            case "sweep":
                pose.nearDegrees=CGFloat(-60+8*sin(t * .pi*1.3))*amount; pose.headDegrees=2*amount
                pose.prop="broom"; pose.propRotation=CGFloat(-20+8*sin(t * .pi*1.3))
            case "bell":
                pose.nearDegrees=CGFloat(-85+12*sin(t * .pi*4))*amount
                pose.prop="bell"; pose.propRotation=CGFloat(18*sin(t * .pi*4))
            case "rest":
                pose.nearDegrees=0; pose.headDegrees=CGFloat(8+0.8*sin(t * .pi/5))*amount
            case "incense":
                pose.nearDegrees = -47*amount; pose.farDegrees=22*amount; pose.farScale=1-0.2*amount
                pose.headDegrees=6*amount; pose.prop="incense"
            case "paper":
                pose.nearDegrees = -61*amount; pose.headDegrees=2*amount; pose.prop="paper"
            case "response":
                pose.nearDegrees = -40*amount; pose.farDegrees=24*amount; pose.farScale=1-0.2*amount; pose.headDegrees=6*amount
            default:return .zero
            }
            if pose.prop != nil { pose.propScale=amount; pose.propAmount=amount }
            return pose
        }
        func parts(_ pose:GesturePose,feet:[Part]?,net:FixedCatch?,unitToView:CGFloat,
                   offeringFrame:Frame?)->[Part] {
            let nearTransform=AttendantArtwork.rotation(pose.nearDegrees,about:nearPivot)
            let farScale=CGAffineTransform(a:pose.farScale,b:0,c:0,d:pose.farScale,
                tx:farPivot.x*(1-pose.farScale),ty:farPivot.y*(1-pose.farScale))
            let farTransform=AttendantArtwork.compose(farScale,AttendantArtwork.rotation(pose.farDegrees,about:farPivot))
            let hand=nearHand.applying(nearTransform)
            let arm=Part(frame:near.frame,bounds:near.bounds,transform:nearTransform)
            var parts=(feet ?? [])+[underlay,feet != nil ? (upperBase ?? base):base,
                Part(frame:head.frame,bounds:head.bounds,transform:AttendantArtwork.rotation(pose.headDegrees,about:headPivot)),
                Part(frame:far.frame,bounds:far.bounds,transform:farTransform)]
            if pose.prop=="net",let net,pose.propAmount>0.000001 {
                let h=net.netHeight*pose.propScale,w=h*CGFloat(net.net.width)/CGFloat(net.net.height)
                parts.append(Part(frame:net.net,bounds:NSRect(x:hand.x-net.grip.x*w,y:hand.y-net.grip.y*h,width:w,height:h),
                    transform:AttendantArtwork.rotation(net.netRotation+pose.nearDegrees,about:hand),fraction:pose.propAmount))
                parts.append(arm)
                return parts
            }
            parts.append(arm)
            if let name=pose.prop,let original=props[name],pose.propAmount>0.000001 {
                let prop:LoadedProp
                if name=="fruit",let offeringFrame {
                    // Shrine images retain their authored canvas but inherit the
                    // character's source facing before the shared world mirror.
                    let frame=Frame(image:offeringFrame.image,alpha:offeringFrame.alpha,
                        width:offeringFrame.width,height:offeringFrame.height,
                        facesLeft:original.frame.facesLeft,interpolation:offeringFrame.interpolation)
                    prop=LoadedProp(frame:frame,coreBounds:NSRect(x:0,y:0,width:frame.width,height:frame.height),
                        height:original.height,grip:original.grip,rotation:original.rotation,
                        minCoreWidth:0,groundY:nil)
                } else { prop=original }
                let angle=prop.rotation+pose.propRotation
                let height:CGFloat
                if let ground=prop.groundY {
                    let denominator=(1-prop.grip.y)*cos(angle * .pi/180)
                    height=denominator>0.01 ? max(0,(ground-hand.y)/denominator):0
                } else { height=(prop.height ?? 0)*pose.propScale }
                let width=prop.width(height:height,unitToView:unitToView)
                if height>0 && width>0 {
                    parts.append(Part(frame:prop.frame,bounds:NSRect(x:hand.x-prop.grip.x*width,y:hand.y-prop.grip.y*height,width:width,height:height),
                        transform:AttendantArtwork.rotation(angle,about:hand),fraction:pose.propAmount))
                    parts.append(Part(frame:handCover.frame,bounds:handCover.bounds,transform:nearTransform))
                }
            }
            return parts
        }
    }
    private static func alphaBounds(_ frame:Frame,threshold:UInt8)->NSRect? {
        var minX=frame.width,minY=frame.height,maxX = -1,maxY = -1
        for y in 0..<frame.height { for x in 0..<frame.width where frame.alpha[y*frame.width+x]>threshold {
            minX=min(minX,x); minY=min(minY,y); maxX=max(maxX,x); maxY=max(maxY,y)
        }}
        return maxX>=minX && maxY>=minY ? NSRect(x:minX,y:minY,width:maxX-minX+1,height:maxY-minY+1):nil
    }
    // Mask once while loading. A tight crop is safe only after placement has
    // been resolved; the net's authored canvas is intentionally kept intact.
    private static func masked(_ frame: Frame, bounds: NSRect, keeping: (NSPoint)->Bool) -> Part? {
        var alpha=frame.alpha, mask=[UInt8](repeating:255,count:frame.width*frame.height)
        var minX=frame.width,minY=frame.height,maxX = -1,maxY = -1
        for y in 0..<frame.height { for x in 0..<frame.width {
            let index=y*frame.width+x
            let p=NSPoint(x:bounds.minX+(CGFloat(x)+0.5)*bounds.width/CGFloat(frame.width),
                          y:bounds.minY+(CGFloat(y)+0.5)*bounds.height/CGFloat(frame.height))
            if keeping(p) { mask[index]=0 } else { alpha[index]=0 }
            if alpha[index] > 0 { minX=min(minX,x); minY=min(minY,y); maxX=max(maxX,x); maxY=max(maxY,y) }
        }}
        var proposed=NSRect(x:0,y:0,width:frame.width,height:frame.height)
        guard maxX >= minX,maxY >= minY,let image=frame.image.cgImage(forProposedRect:&proposed,context:nil,hints:nil),
              let provider=CGDataProvider(data:Data(mask) as CFData),
              let clip=CGImage(maskWidth:frame.width,height:frame.height,bitsPerComponent:8,bitsPerPixel:8,
                               bytesPerRow:frame.width,provider:provider,decode:nil,shouldInterpolate:false),
              let clipped=image.masking(clip),
              let cropped=clipped.cropping(to:NSRect(x:minX,y:minY,width:maxX-minX+1,height:maxY-minY+1)) else { return nil }
        let w=maxX-minX+1,h=maxY-minY+1
        var result=[UInt8](); result.reserveCapacity(w*h)
        for y in minY...maxY { result.append(contentsOf:alpha[(y*frame.width+minX)...(y*frame.width+maxX)]) }
        let sx=bounds.width/CGFloat(frame.width),sy=bounds.height/CGFloat(frame.height)
        return Part(frame:Frame(image:NSImage(cgImage:cropped,size:NSSize(width:w,height:h)),alpha:result,
            width:w,height:h,facesLeft:frame.facesLeft,interpolation:frame.interpolation),
            bounds:NSRect(x:bounds.minX+CGFloat(minX)*sx,y:bounds.minY+CGFloat(minY)*sy,width:CGFloat(w)*sx,height:CGFloat(h)*sy))
    }
    private struct FixedWalk {
        let stand: Frame
        let body: Part, left: Part, right: Part
        let maxRootStep: CGFloat, footLift: CGFloat
        init?(_ spec: FixedWalkSpec, stand: Frame) {
            guard spec.sourceSize == [stand.width, stand.height],
                  spec.legStartY >= 0, spec.legStartY < spec.bodyCutY, spec.bodyCutY < stand.height,
                  spec.legSplitX > 0, spec.legSplitX < stand.width,
                  spec.maxRootStep.isFinite, spec.maxRootStep > 0,
                  spec.maxRootStep <= Double(stand.width)/2,
                  spec.footLift.isFinite, spec.footLift >= 0,
                  spec.footLift <= Double(stand.height-spec.bodyCutY) else { return nil }
            var proposed = NSRect(x: 0, y: 0, width: stand.width, height: stand.height)
            guard let image = stand.image.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else { return nil }
            func part(_ x: Int, _ y: Int, _ w: Int, _ h: Int) -> Part? {
                let box = NSRect(x: x, y: y, width: w, height: h)
                guard let crop = image.cropping(to: box) else { return nil }
                var mask = [UInt8](); mask.reserveCapacity(w*h)
                for row in y..<(y+h) { mask.append(contentsOf: stand.alpha[(row*stand.width+x)..<(row*stand.width+x+w)]) }
                guard mask.contains(where: { $0 > 16 }) else { return nil }
                return Part(frame: Frame(image: NSImage(cgImage: crop, size: box.size), alpha: mask,
                    width: w, height: h, facesLeft: stand.facesLeft, interpolation: stand.interpolation), bounds: box)
            }
            guard let body = part(0, 0, stand.width, spec.bodyCutY),
                  let left = part(0, spec.legStartY, spec.legSplitX, stand.height-spec.legStartY),
                  let right = part(spec.legSplitX, spec.legStartY, stand.width-spec.legSplitX, stand.height-spec.legStartY) else { return nil }
            self.stand=stand; self.body=body; self.left=left; self.right=right
            maxRootStep=CGFloat(spec.maxRootStep); footLift=CGFloat(spec.footLift)
        }
        func offsets(distance: CGFloat, totalDistance: CGFloat, displayHeight: CGFloat) -> WalkOffsets {
            guard distance.isFinite, totalDistance.isFinite, displayHeight.isFinite,
                  totalDistance > 0, displayHeight > 0 else { return .zero }
            let unit = CGFloat(stand.height)/displayHeight
            let total = totalDistance*unit, travelled = min(total, max(0, distance*unit))
            guard total.isFinite, travelled < total-0.000001 else { return .zero }
            let steps = max(2, 2*ceil(total/(2*maxRootStep)))
            guard steps.isFinite else { return .zero }
            let stride = total/steps, position = travelled/stride
            let index = floor(position), phase = position-index
            let smooth = phase*phase*(3-2*phase)
            let base = 2*floor(index/2)*stride
            let lift = min(footLift, stride*0.4)*sin(.pi*phase)
            if index.truncatingRemainder(dividingBy: 2) < 1 {
                return WalkOffsets(leftX: base+2*stride*smooth-travelled, leftLift: lift,
                                   rightX: base-travelled, rightLift: 0)
            }
            return WalkOffsets(leftX: base+2*stride-travelled, leftLift: 0,
                               rightX: base+2*stride*smooth-travelled, rightLift: lift)
        }
        func rendering(_ offsets: WalkOffsets) -> Rendering {
            if offsets == .zero {
                return Rendering(width: stand.width, height: stand.height,
                    parts: [Part(frame: stand, bounds: NSRect(x:0,y:0,width:stand.width,height:stand.height))])
            }
            let forward: CGFloat = stand.facesLeft ? -1 : 1
            let a = Part(frame: left.frame, bounds: left.bounds.offsetBy(dx: offsets.leftX*forward, dy: -offsets.leftLift))
            let b = Part(frame: right.frame, bounds: right.bounds.offsetBy(dx: offsets.rightX*forward, dy: -offsets.rightLift))
            return Rendering(width: stand.width, height: stand.height,
                parts: offsets.leftLift > offsets.rightLift ? [b,a,body] : [a,b,body])
        }
    }
    private struct Pixels {
        let image: CGImage
        let alpha: [UInt8]
        let bounds: NSRect
        var width: Int { image.width }
        var height: Int { image.height }

        func cropped(to box: NSRect, facesLeft: Bool, interpolation: NSImageInterpolation) -> Frame? {
            guard let source = image.cropping(to: box),let decoded=compactSceneRaster(source) else { return nil }
            let crop=decoded.image
            let x = Int(box.minX), y = Int(box.minY), w = Int(box.width), h = Int(box.height)
            var mask = [UInt8](); mask.reserveCapacity(w * h)
            for row in y..<(y + h) { mask.append(contentsOf: alpha[(row * width + x)..<(row * width + x + w)]) }
            return Frame(image: NSImage(cgImage: crop, size: NSSize(width: w, height: h)),
                         alpha: mask, width: w, height: h, facesLeft: facesLeft, interpolation: interpolation)
        }
    }
    private let stand: Frame
    private let walk: [Frame]
    private let fps: Double
    private let fixedWalk: FixedWalk?
    private let fixedCatch: FixedCatch?
    private let fixedDaily: FixedDaily?
    var hasWalkFrames: Bool { !walk.isEmpty }
    var hasWalkMotion: Bool { hasWalkFrames || fixedWalk != nil }
    var hasCatchMotion: Bool { fixedCatch != nil }
    var hasDailyMotion: Bool { fixedDaily != nil }
    func canPresent(_ action:String)->Bool {
        if action=="idle" { return true }
        if action=="walk" { return hasWalkMotion }
        if action=="catch" { return hasCatchMotion }
        return fixedDaily?.canPresent(action)==true
    }
    func gesture(_ action:String,elapsed:Double,duration:Double)->GesturePose {
        if action=="catch",hasCatchMotion { return .catching(.sample(elapsed)) }
        return fixedDaily?.sample(action,elapsed:elapsed,duration:duration) ?? .zero
    }
    func propFrame(_ name:String)->Frame? { fixedDaily?.props[name]?.frame }
    func propCoreBounds(_ name:String)->NSRect? { fixedDaily?.props[name]?.coreBounds }
    func propWidth(_ name:String,height:CGFloat,unitToView:CGFloat)->CGFloat? {
        fixedDaily?.props[name]?.width(height:height,unitToView:unitToView)
    }

    private init(stand: Frame, walk: [Frame], fps: Double, fixedWalk: FixedWalk?, fixedCatch: FixedCatch?, fixedDaily:FixedDaily?) {
        self.stand = stand; self.walk = walk; self.fps = fps; self.fixedWalk = fixedWalk
        self.fixedCatch = fixedCatch
        self.fixedDaily = fixedDaily
    }
    func fixedWalkOffsets(distance: CGFloat, totalDistance: CGFloat, displayHeight: CGFloat) -> WalkOffsets? {
        fixedWalk?.offsets(distance: distance, totalDistance: totalDistance, displayHeight: displayHeight)
    }
    func rendering(walking: Bool, elapsed: TimeInterval, offsets: WalkOffsets?, catchPose: CatchPose = .zero,
                   gesture:GesturePose?=nil,unitToView:CGFloat=1,offeringFrame:Frame?=nil) -> Rendering {
        let currentGesture=gesture ?? .catching(catchPose)
        let originalCatch=currentGesture.prop=="net" && abs(currentGesture.farDegrees)<0.000001
            && abs(currentGesture.headDegrees)<0.000001 && abs(currentGesture.farScale-1)<0.000001
        if let fixedDaily,!currentGesture.isNeutral,!originalCatch {
            let feet:[Part]?=fixedWalk.flatMap { walk in
                guard let offsets,offsets != .zero else { return nil }
                return Array(walk.rendering(offsets).parts.dropLast())
            }
            return Rendering(width:stand.width,height:stand.height,
                parts:fixedDaily.parts(currentGesture,feet:feet,net:fixedCatch,unitToView:unitToView,offeringFrame:offeringFrame))
        }
        let catchSample=gesture.map { CatchPose(degrees:$0.nearDegrees,visibility:$0.prop == "net" ? $0.propAmount:0) } ?? catchPose
        if let fixedCatch, catchSample.visibility > 0.000001 {
            let feet: [Part]? = fixedWalk.flatMap { walk in
                guard let offsets, offsets != .zero else { return nil }
                return Array(walk.rendering(offsets).parts.dropLast())
            }
            return Rendering(width:stand.width,height:stand.height,parts:fixedCatch.parts(catchSample,feet:feet))
        }
        if let fixedWalk, let offsets { return fixedWalk.rendering(offsets) }
        let current = frame(walking: walking, elapsed: elapsed)
        return Rendering(width: current.width, height: current.height,
            parts: [Part(frame: current, bounds: NSRect(x:0,y:0,width:current.width,height:current.height))])
    }
    func frame(walking: Bool, elapsed: TimeInterval) -> Frame {
        guard walking, !walk.isEmpty, elapsed.isFinite, elapsed >= 0 else { return stand }
        let phase = (elapsed * fps).truncatingRemainder(dividingBy: Double(walk.count))
        return walk[Int(phase)]
    }
    static func load(from directory: URL? = Bundle.main.resourceURL?.appendingPathComponent("art/A01", isDirectory: true)) -> AttendantArtwork? {
        guard let directory,
              let manifestURL = safeURL("manifest.json", in: directory),
              let data = try? Data(contentsOf: manifestURL),
              let manifest = try? JSONDecoder().decode(Manifest.self, from: data), manifest.version == 1,
              validFacing(manifest.stand.facing),
              let pixels = read(manifest.stand, in: directory),
              let stand = pixels.cropped(to: pixels.bounds, facesLeft: manifest.stand.facing == "left",
                                         interpolation: (manifest.sampling ?? .smooth).interpolation) else { return nil }
        var frames: [Frame] = []
        var fps: Double = 6
        if let walk = manifest.walk, validFacing(walk.facing), walk.fps.isFinite,
           walk.fps > 0, walk.fps <= 60, (2...64).contains(walk.frames.count) {
            // Equal source canvases and one union crop preserve foot alignment
            // and scale when a lifted foot changes an individual frame's bounds.
            let decoded = walk.frames.compactMap { read($0, in: directory) }
            if decoded.count == walk.frames.count, let first = decoded.first,
               decoded.allSatisfy({ $0.width == first.width && $0.height == first.height }) {
                let union = decoded.reduce(NSRect.null) { $0.union($1.bounds) }
                frames = decoded.compactMap { $0.cropped(to: union, facesLeft: walk.facing == "left",
                                                        interpolation: (manifest.sampling ?? .smooth).interpolation) }
                fps = walk.fps
            }
        }
        let fixedWalk=manifest.fixedWalk.flatMap { FixedWalk($0,stand:stand) }
        let fixedCatch=manifest.fixedActions.flatMap { FixedCatch($0,stand:stand,fixedWalk:fixedWalk,directory:directory) }
        let fixedDaily=manifest.fixedActions.flatMap { FixedDaily($0,stand:stand,fixedWalk:fixedWalk,directory:directory) }
        return AttendantArtwork(stand:stand,walk:frames,fps:fps,fixedWalk:fixedWalk,fixedCatch:fixedCatch,fixedDaily:fixedDaily)
    }
    private static func validFacing(_ facing: String?) -> Bool {
        facing == nil || facing == "left" || facing == "right"
    }
    private static func safeURL(_ name: String, in directory: URL) -> URL? {
        guard !name.isEmpty, !NSString(string: name).isAbsolutePath,
              !name.split(separator: "/").contains("..") else { return nil }
        let root = directory.resolvingSymlinksInPath().standardizedFileURL
        let file = root.appendingPathComponent(name).resolvingSymlinksInPath().standardizedFileURL
        guard file.path.hasPrefix(root.path + "/") else { return nil }
        return file
    }
    private static func read(_ spec: FrameSpec, in directory: URL) -> Pixels? {
        guard let url = safeURL(spec.file, in: directory), url.pathExtension.lowercased() == "png",
              let data = try? Data(contentsOf: url), data.starts(with:[137,80,78,71,13,10,26,10]), let rep = NSBitmapImageRep(data: data),
              rep.hasAlpha, var image = rep.cgImage else { return nil }
        if let values = spec.sourceRect {
            guard values.count == 4, values[0] >= 0, values[1] >= 0, values[2] > 0, values[3] > 0,
                  values[0] < image.width, values[1] < image.height,
                  values[2] <= image.width - values[0], values[3] <= image.height - values[1],
                  let crop = image.cropping(to: NSRect(x: values[0], y: values[1], width: values[2], height: values[3])) else { return nil }
            image = crop
        }
        guard let decoded=compactSceneRaster(image) else { return nil }
        image=decoded.image
        let width = image.width, height = image.height
        let alpha = decoded.alpha
        var minX = width, minY = height, maxX = -1, maxY = -1
        for y in 0..<height { for x in 0..<width {
            let value = alpha[y * width + x]
            if value > 0 { minX = min(minX, x); minY = min(minY, y); maxX = max(maxX, x); maxY = max(maxY, y) }
        } }
        guard maxX >= minX, maxY >= minY else { return nil }
        return Pixels(image: image, alpha: alpha,
                      bounds: NSRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1))
    }
}

// A pure display value shared by the desktop and the shop preview. It does
// not know ownership, price, transactions, or persistence.
struct SceneAppearance: Equatable {
    static let slots = ["plate", "incense", "bell", "shrine"]
    private static let itemSlots = ["offering_plate":"plate", "incense_burner":"incense",
                                    "bell":"bell", "shrine_g1":"shrine", "shrine_g2":"shrine"]
    private var items: [String:String] = [:]
    init(snapshot: [String:Any] = [:]) {
        if let raw = snapshot["placed_items"] {
            // Presence, including an empty or malformed value, is authoritative.
            if let placed = raw as? [String:Any] {
                for (slot,value) in placed {
                    if let id = value as? String, Self.itemSlots[id] == slot { items[slot] = id }
                }
            }
            return
        }
        if let shop = snapshot["shop"] as? [[String:Any]] {
            for row in shop {
                guard let id = row["id"] as? String, let slot = Self.itemSlots[id],
                      let placed = row["placed"] as? NSNumber,
                      CFGetTypeID(placed) == CFBooleanGetTypeID(), placed.boolValue else { continue }
                items[slot] = id
            }
        }
        if items["shrine"] == nil, let stage = snapshot["shrine_stage"] as? NSNumber,
           CFGetTypeID(stage) != CFBooleanGetTypeID(), [1.0,2.0].contains(stage.doubleValue) {
            items["shrine"] = stage.intValue == 1 ? "shrine_g1":"shrine_g2"
        }
    }
    func itemID(in slot:String) -> String? { items[slot] }
    func previewing(itemID:String) -> SceneAppearance {
        guard let slot = Self.itemSlots[itemID] else { return self }
        var result = self; result.items[slot] = itemID; return result
    }
    func resetting(slot:String) -> SceneAppearance {
        var result = self; result.items.removeValue(forKey:slot); return result
    }
}

// The four accepted base layers remain atomic. Optional paid appearances are
// validated separately, so one unavailable item falls back only in its slot.
final class ShrineArtwork {
    static let shared = ShrineArtwork.load()
    private struct ImageSpec: Decodable {
        let file: String
        let sourceRect: [Int]?
    }
    private struct LayerSpec: Decodable {
        let id: String
        let file: String
        let sourceRect: [Int]?
        let bounds: [Double]
    }
    private struct AppearanceSpec: Decodable {
        let layers: [LayerSpec]
        let fruitVariants: [String:ImageSpec]?
        let incenseAnchor: [Double]?
    }
    private struct OptionalAppearance: Decodable {
        let value: AppearanceSpec?
        init(from decoder: Decoder) throws { value = try? AppearanceSpec(from:decoder) }
    }
    private struct Manifest: Decodable {
        let version: Int
        let sampling: String
        let layers: [LayerSpec]
        let attendantHeight: Double?
        let fruitVariants: [String: ImageSpec]?
        let appearances: [String:OptionalAppearance]
        let incenseAnchor: [Double]?
        private enum CodingKeys:String,CodingKey {
            case version,sampling,layers,attendantHeight,fruitVariants,appearances,incenseAnchor
        }
        init(from decoder:Decoder) throws {
            let c=try decoder.container(keyedBy:CodingKeys.self)
            version=try c.decode(Int.self,forKey:.version)
            sampling=try c.decode(String.self,forKey:.sampling)
            layers=try c.decode([LayerSpec].self,forKey:.layers)
            attendantHeight=try c.decodeIfPresent(Double.self,forKey:.attendantHeight)
            fruitVariants=try c.decodeIfPresent([String:ImageSpec].self,forKey:.fruitVariants)
            appearances=(try? c.decode([String:OptionalAppearance].self,forKey:.appearances)) ?? [:]
            incenseAnchor=try? c.decode([Double].self,forKey:.incenseAnchor)
        }
    }
    struct Layer {
        let id: String
        let frame: AttendantArtwork.Frame
        let bounds: NSRect
    }
    struct Selection {
        let layers: [Layer]
        let freshOfferingFrame: AttendantArtwork.Frame
        let incenseAnchor: NSPoint
        let unavailableIDs: Set<String>
        var bounds: NSRect { layers.reduce(NSRect.null) { $0.union($1.bounds) } }
        func contains(_ point:NSPoint) -> Bool {
            layers.contains { $0.frame.contains(point,in:$0.bounds,mirrored:false) }
        }
    }
    private struct Appearance {
        let layers: [Layer]
        let fruitVariants: [String:AttendantArtwork.Frame]
        let incenseAnchor: NSPoint?
    }
    let layers: [Layer]
    let bounds: NSRect
    let attendantHeight: CGFloat
    private let fruitVariants: [String: AttendantArtwork.Frame]
    private let appearances: [String:Appearance]
    private let baseIncenseAnchor: NSPoint
    var availableAppearanceIDs: Set<String> { Set(appearances.keys) }

    private init(layers:[Layer],attendantHeight:CGFloat,fruitVariants:[String:AttendantArtwork.Frame],
                 appearances:[String:Appearance],incenseAnchor:NSPoint) {
        self.layers=layers; self.bounds=layers.reduce(NSRect.null) { $0.union($1.bounds) }
        self.attendantHeight=attendantHeight; self.fruitVariants=fruitVariants
        self.appearances=appearances; self.baseIncenseAnchor=incenseAnchor
    }
    func resolve(appearance:SceneAppearance,fruitStage:String?,heldBellVisible:Bool=false) -> Selection {
        var selected=layers,variants=fruitVariants,anchor=baseIncenseAnchor,unavailable=Set<String>()
        for slot in SceneAppearance.slots {
            guard let id=appearance.itemID(in:slot) else { continue }
            guard let entry=appearances[id] else { unavailable.insert(id); continue }
            for replacement in entry.layers {
                if let index=selected.firstIndex(where:{$0.id==replacement.id}) { selected[index]=replacement }
                else { selected.append(replacement) }
            }
            if slot=="plate" { variants=entry.fruitVariants }
            if slot=="incense",let authored=entry.incenseAnchor { anchor=authored }
        }
        let fresh=variants["fresh"] ?? selected.first{$0.id=="fruit"}!.frame
        if let frame=variants[fruitStage ?? "fresh"] {
            selected=selected.map { $0.id=="fruit" ? Layer(id:$0.id,frame:frame,bounds:$0.bounds):$0 }
        }
        if heldBellVisible { selected.removeAll{$0.id=="bell"} }
        return Selection(layers:selected,freshOfferingFrame:fresh,incenseAnchor:anchor,unavailableIDs:unavailable)
    }
    func layers(for fruitStage:String?) -> [Layer] {
        resolve(appearance:SceneAppearance(),fruitStage:fruitStage).layers
    }
    func layer(id:String) -> Layer? { layers.first{$0.id==id} }
    func contains(_ point:NSPoint,fruitStage:String?) -> Bool {
        resolve(appearance:SceneAppearance(),fruitStage:fruitStage).contains(point)
    }
    static func load(from directory:URL? = Bundle.main.resourceURL?.appendingPathComponent("art/scene",isDirectory:true)) -> ShrineArtwork? {
        guard let directory,let manifestURL=safeURL("manifest.json",in:directory),let data=try? Data(contentsOf:manifestURL),
              let manifest=try? JSONDecoder().decode(Manifest.self,from:data),manifest.version==1,manifest.sampling=="nearest",
              manifest.layers.count==4,Set(manifest.layers.map{$0.id})==Set(["shrine","idol","incense","fruit"]) else { return nil }
        let height=manifest.attendantHeight ?? 170
        guard height.isFinite,height>0,height<=310-Double(TianmuView.sceneCanvas.minY) else { return nil }
        func loadLayers(_ specs:[LayerSpec]) -> [Layer]? {
            var loaded:[Layer]=[]
            for spec in specs {
                guard let bounds=designBounds(spec.bounds),let frame=read(file:spec.file,sourceRect:spec.sourceRect,in:directory) else { return nil }
                loaded.append(Layer(id:spec.id,frame:frame,bounds:bounds))
            }; return loaded
        }
        func loadFruit(_ specs:[String:ImageSpec]) -> [String:AttendantArtwork.Frame]? {
            guard Set(specs.keys).isSubset(of:Set(["fresh","soft","ripe"])) else { return nil }
            var loaded:[String:AttendantArtwork.Frame]=[:]
            for (stage,spec) in specs {
                guard let frame=read(file:spec.file,sourceRect:spec.sourceRect,in:directory) else { return nil }
                loaded[stage]=frame
            }; return loaded
        }
        func anchor(_ values:[Double]?,layer:Layer) -> NSPoint? {
            guard let values,values.count==2,values.allSatisfy({$0.isFinite && (0...1).contains($0)}) else { return nil }
            return NSPoint(x:layer.bounds.minX+CGFloat(values[0])*layer.bounds.width,
                           y:layer.bounds.minY+CGFloat(values[1])*layer.bounds.height)
        }
        guard let layers=loadLayers(manifest.layers),let fruit=loadFruit(manifest.fruitVariants ?? [:]),
              let censer=layers.first(where:{$0.id=="incense"}) else { return nil }
        let baseAnchor=anchor(manifest.incenseAnchor,layer:censer) ?? anchor([0.5,0.24],layer:censer)!
        let required:[String:Set<String>]=["shrine_g1":["shrine"],"shrine_g2":["shrine","idol"],
            "offering_plate":["fruit"],"incense_burner":["incense"],"bell":["bell"]]
        var appearances:[String:Appearance]=[:]
        for (id,ids) in required {
            guard let spec=manifest.appearances[id]?.value,spec.layers.count==ids.count,
                  Set(spec.layers.map{$0.id})==ids,let selected=loadLayers(spec.layers) else { continue }
            var variants:[String:AttendantArtwork.Frame]=[:]
            if let entries=spec.fruitVariants {
                guard Set(entries.keys)==Set(["fresh","soft","ripe"]),let loaded=loadFruit(entries) else { continue }
                if id=="offering_plate" { variants=loaded }
            } else if id=="offering_plate" { continue }
            var selectedAnchor:NSPoint?
            if spec.incenseAnchor != nil {
                guard let authored=anchor(spec.incenseAnchor,layer:selected[0]) else { continue }
                if id=="incense_burner" { selectedAnchor=authored }
            } else if id=="incense_burner" { continue }
            appearances[id]=Appearance(layers:selected,fruitVariants:variants,incenseAnchor:selectedAnchor)
        }
        return ShrineArtwork(layers:layers,attendantHeight:CGFloat(height),fruitVariants:fruit,
                             appearances:appearances,incenseAnchor:baseAnchor)
    }
    private static func designBounds(_ values: [Double]) -> NSRect? {
        guard values.count == 4, values.allSatisfy({ $0.isFinite }), values[2] > 0, values[3] > 0 else { return nil }
        let canvas = TianmuView.sceneCanvas
        guard values[0] >= Double(canvas.minX), values[1] >= Double(canvas.minY),
              values[2] <= Double(canvas.maxX) - values[0],
              values[3] <= Double(canvas.maxY) - values[1] else { return nil }
        return NSRect(x: values[0], y: values[1], width: values[2], height: values[3])
    }
    private static func safeURL(_ name: String, in directory: URL) -> URL? {
        guard !name.isEmpty, !NSString(string: name).isAbsolutePath, !name.contains("/"),
              name != ".", name != ".." else { return nil }
        let root = directory.resolvingSymlinksInPath().standardizedFileURL
        let file = root.appendingPathComponent(name).resolvingSymlinksInPath().standardizedFileURL
        guard file.deletingLastPathComponent().path == root.path else { return nil }
        return file
    }
    private static func read(file name: String, sourceRect: [Int]?, in directory: URL) -> AttendantArtwork.Frame? {
        guard let url = safeURL(name, in: directory), url.pathExtension.lowercased() == "png",
              let data = try? Data(contentsOf: url), data.starts(with: [137, 80, 78, 71, 13, 10, 26, 10]),
              let rep = NSBitmapImageRep(data: data), rep.hasAlpha, var image = rep.cgImage else { return nil }
        if let box = sourceRect {
            guard box.count == 4, box[0] >= 0, box[1] >= 0, box[2] > 0, box[3] > 0,
                  box[0] < image.width, box[1] < image.height,
                  box[2] <= image.width - box[0], box[3] <= image.height - box[1],
                  let crop = image.cropping(to: NSRect(x: box[0], y: box[1], width: box[2], height: box[3])) else { return nil }
            image = crop
        }
        guard let decoded=compactSceneRaster(image) else { return nil }
        image=decoded.image
        let width = image.width, height = image.height
        let alpha = decoded.alpha
        guard alpha.contains(where: { $0 > 0 }) else { return nil }
        return AttendantArtwork.Frame(image: NSImage(cgImage: image, size: NSSize(width: width, height: height)),
                                      alpha: alpha, width: width, height: height, facesLeft: false, interpolation: .none)
    }
}

// A presentation of service facts, driven only by the host's existing clock.
// It never schedules work or treats a missing animation as a performed action.
struct RoutinePresentation {
    struct Snapshot {
        let action: String
        let serial: Int
        let elapsed: Double
        let duration: Double
        let fruitStage: String
        init?(_ raw: [String: Any]) {
            func number(_ key: String) -> Double? {
                guard let value = raw[key] as? NSNumber,
                      CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return nil }
                return value.doubleValue
            }
            guard let action = raw["action"] as? String,
                  ["idle", "walk", "sweep", "read", "rest", "practice", "offer", "catch", "bell"].contains(action),
                  let fruit = raw["fruit_stage"] as? String, ["fresh", "soft", "ripe"].contains(fruit),
                  let serial = number("action_serial"), serial >= 0, serial < Double(Int.max), serial.rounded(.towardZero) == serial,
                  let duration = number("action_duration"), duration >= 0,
                  let elapsed = number("action_elapsed"), elapsed >= 0, elapsed <= duration,
                  let progress = number("progress"), (0...1).contains(progress),
                  duration == 0 || abs(progress - elapsed / duration) < 0.00001 else { return nil }
            self.action = action; self.serial = Int(serial); self.duration = duration
            self.elapsed = elapsed; self.fruitStage = fruit
        }
    }
    struct Pose {
        var x: CGFloat = 355
        var direction: CGFloat = -1
        var walking = false
        var frameElapsed: Double = 0
        var travelDistance: CGFloat = 0
        var totalDistance: CGFloat = 0
        var action = "idle"
        var serial: Int = 0
        var duration: Double = 0
    }
    private(set) var snapshot: Snapshot?
    private var walkAvailable = false
    private var receivedAt: Double = 0
    private var anchorElapsed: Double = 0
    private var startProgress: Double = 0
    private var startX: CGFloat = 355
    private var targetX: CGFloat = 355
    private var journeyStartX: CGFloat = 355
    private var direction: CGFloat = -1
    private var held: Pose?

    private func elapsed(at clock: Double) -> Double {
        guard let snapshot else { return 0 }
        // One service heartbeat of interpolation; a stopped feed cannot invent
        // continued work, a completed walk or another loop.
        return min(snapshot.duration, anchorElapsed + min(1, max(0, clock - receivedAt)))
    }
    private func progress(at clock: Double) -> Double {
        guard let snapshot, snapshot.duration > 0 else { return 0 }
        return elapsed(at: clock) / snapshot.duration
    }
    func pose(at clock: Double) -> Pose {
        if let held { return held }
        guard let snapshot else { return Pose() }
        guard walkAvailable, snapshot.action == "walk" else {
            return Pose(x:startX,direction:direction,frameElapsed:elapsed(at:clock),
                        action:snapshot.action,serial:snapshot.serial,duration:snapshot.duration)
        }
        let p = progress(at: clock)
        let fraction = startProgress < 1 ? min(1, max(0, (p - startProgress) / (1 - startProgress))) : 0
        let eased = CGFloat(fraction * fraction * (3 - 2 * fraction))
        let x = startX + (targetX - startX) * eased
        return Pose(x: x, direction: direction, walking: p < 1, frameElapsed: elapsed(at: clock),
                    travelDistance: abs(x-journeyStartX), totalDistance: abs(targetX-journeyStartX),
                    action:snapshot.action,serial:snapshot.serial,duration:snapshot.duration)
    }
    private mutating func rebase(from x: CGFloat, at clock: Double, chooseDestination: Bool = false) {
        startX = x; startProgress = progress(at: clock)
        if chooseDestination {
            journeyStartX = x
            targetX = walkAvailable && snapshot?.action == "walk" ? (x > 326.5 ? 290 : 363) : x
        }
        if targetX != x { direction = targetX > x ? 1 : -1 }
    }
    mutating func setWalkAvailable(_ available: Bool, at clock: Double) {
        guard available != walkAvailable else { return }
        let current = pose(at: clock)
        walkAvailable = available
        rebase(from: current.x, at: clock, chooseDestination: true)
    }
    mutating func setInterrupted(_ interrupted: Bool, at clock: Double) {
        if interrupted {
            if held == nil { held = pose(at: clock) }
        } else if let frozen = held {
            held = nil
            rebase(from: frozen.x, at: clock)
        }
    }
    mutating func apply(_ raw: [String: Any]?, at clock: Double) -> Bool {
        guard let raw, let next = Snapshot(raw) else { return false }
        if let previous = snapshot {
            guard next.serial >= previous.serial else { return false }
            if next.serial == previous.serial {
                guard next.action == previous.action, next.duration == previous.duration,
                      next.elapsed >= previous.elapsed else { return false }
                if next.elapsed > previous.elapsed {
                    anchorElapsed = max(elapsed(at: clock), next.elapsed)
                    receivedAt = clock
                }
                snapshot = next  // Fruit can mature without restarting an action.
                return true
            }
        }
        let current = pose(at: clock)
        snapshot = next; anchorElapsed = next.elapsed; receivedAt = clock
        rebase(from: current.x, at: clock, chooseDestination: true)
        return true
    }
}

final class SceneAccessibleButton: NSAccessibilityElement {
    var press: (() -> Void)?
    var showMenu: (() -> Void)?
    override func accessibilityPerformPress() -> Bool { press?(); return press != nil }
    override func accessibilityPerformShowMenu() -> Bool { showMenu?(); return showMenu != nil }
}

final class TianmuView: NSView {
    // The logical scene is cropped around the visible shrine and attendant.
    // Hosts use this size at 100%; source artwork retains its original coordinates.
    static let sceneCanvas = NSRect(x: 55, y: 130, width: 370, height: 190)
    var attendantArtwork: AttendantArtwork? = AttendantArtwork.shared {
        didSet {
            walkTransition = nil; heldWalkOffsets = nil
            displayTransition = nil; heldDisplayPose = nil
            routinePresentation.setWalkAvailable(attendantArtwork?.hasWalkMotion == true, at: animationClock)
            needsDisplay = true
        }
    }
    var shrineArtwork: ShrineArtwork? = ShrineArtwork.shared { didSet { needsDisplay = true } }
    // Embedded shop previews paint their own paper; desktop scenes remain transparent.
    var previewBackgroundColor: NSColor? { didSet { needsDisplay = true } }
    private(set) var routinePresentation = RoutinePresentation()
    private var usesServiceRoutine = false
    @discardableResult func applyRoutine(_ raw: [String: Any]?) -> Bool {
        let previousSerial = routinePresentation.snapshot?.serial
        let previousFeet = resolvedWalkOffsets()
        let previousDisplay = resolvedDisplayPose()
        usesServiceRoutine = true
        routinePresentation.setWalkAvailable(attendantArtwork?.hasWalkMotion == true, at: animationClock)
        syncRoutinePriority()
        let accepted = routinePresentation.apply(raw, at: animationClock)
        if accepted, previousSerial != routinePresentation.snapshot?.serial, !routineInterrupted {
            beginWalkTransition(from: previousFeet)
            if !previousDisplay.gesture.isNeutral { beginDisplayTransition(from:previousDisplay) }
        }
        needsDisplay = true
        return accepted
    }
    var unavailableRoutineAction: String? {
        guard let action = routinePresentation.snapshot?.action, action != "idle" else { return nil }
        if attendantArtwork?.canPresent(action)==true { return nil }
        return action
    }
    private func syncRoutinePriority() {
        let previousDisplay=resolvedDisplayPose()
        let pressed=subjectPress != nil
        let ritualChanged=ritualStage != displayRitualStage || (ritualStage != nil && ritualStarted != displayRitualStarted)
        let ceremonyChanged=(ceremonyElapsed != nil) != (displayCeremonyElapsed != nil)
        let responseChanged=ceremonyElapsed == nil && displayCeremonyElapsed == nil && ritualStage == nil && displayRitualStage == nil && responseStarted != displayResponseStarted
        let displayChanged=pressed != displayPressed || ritualChanged || ceremonyChanged || responseChanged
        if pressed && !displayPressed {
            heldLegacyPose=attendantPose(); heldDisplayPose=previousDisplay; heldSceneAppearance=sceneAppearance
        }
        if !pressed && displayPressed { heldDisplayPose=nil; heldLegacyPose=nil; heldSceneAppearance=nil }
        displayPressed=pressed; displayRitualStage=ritualStage; displayRitualStarted=ritualStarted
        displayResponseStarted=responseStarted; displayCeremonyElapsed=ceremonyElapsed
        let interrupted = subjectPress != nil || ceremonyElapsed != nil || ritualStage != nil || responseStarted != nil
        let previousFeet = interrupted != routineInterrupted ? resolvedWalkOffsets() : nil
        routinePresentation.setInterrupted(interrupted, at: animationClock)
        if interrupted != routineInterrupted {
            routineInterrupted = interrupted
            if interrupted { heldWalkOffsets = previousFeet }
            else { heldWalkOffsets = nil; beginWalkTransition(from: previousFeet) }
        }
        if displayChanged && !pressed { beginDisplayTransition(from:previousDisplay) }
    }
    private struct SceneRitualPose:Equatable {
        var incense:CGFloat=0,smoke:CGFloat=0,phase:CGFloat=0
        // nil preserves the old three-stage fixtures; 0...1 is one carried
        // original incense sprite travelling from the hand into the censer.
        var handTransfer:CGFloat?
        static let zero=SceneRitualPose()
        func interpolated(to next:SceneRitualPose,fraction:CGFloat)->SceneRitualPose {
            let t=min(1,max(0,fraction))
            return SceneRitualPose(incense:incense+(next.incense-incense)*t,
                smoke:smoke+(next.smoke-smoke)*t,phase:phase+(next.phase-phase)*t,
                handTransfer:handTransfer.map { start in next.handTransfer.map { start+($0-start)*t } ?? start } ?? next.handTransfer)
        }
    }
    private struct CeremonyPlacement:Equatable {
        var x:CGFloat,direction:CGFloat,distance:CGFloat=0,totalDistance:CGFloat=0
        func interpolated(to next:CeremonyPlacement,fraction:CGFloat)->CeremonyPlacement {
            let t=min(1,max(0,fraction))
            return CeremonyPlacement(x:x+(next.x-x)*t,direction:t<0.5 ? direction:next.direction,
                distance:distance+(next.distance-distance)*t,totalDistance:totalDistance+(next.totalDistance-totalDistance)*t)
        }
    }
    private struct DisplayPose:Equatable {
        var gesture=AttendantArtwork.GesturePose.zero
        var scene=SceneRitualPose.zero
        var offeringFrame:AttendantArtwork.Frame?
        var placement:CeremonyPlacement?
        static func ==(lhs:DisplayPose,rhs:DisplayPose)->Bool {
            lhs.gesture==rhs.gesture && lhs.scene==rhs.scene && lhs.placement==rhs.placement && lhs.offeringFrame?.image === rhs.offeringFrame?.image
        }
    }
    private var displayCeremonyElapsed:TimeInterval?
    private var ceremonyOrigin=CGFloat(355)
    private var displayPressed=false
    private var displayRitualStage:String?
    private var displayRitualStarted:TimeInterval=0
    private var displayResponseStarted:TimeInterval?
    private var heldDisplayPose:DisplayPose?
    private var heldSceneAppearance:SceneAppearance?
    private var appearanceBeforeChange:DisplayPose?
    private var heldLegacyPose:AttendantPose?
    private var displayTransition:(from:DisplayPose,started:TimeInterval)?
    private func targetDisplayPose()->DisplayPose {
        guard let artwork=attendantArtwork else { return DisplayPose() }
        var result=DisplayPose()
        if let elapsed=displayCeremonyElapsed {
            return ceremonyDisplayPose(elapsed:elapsed,artwork:artwork)
        } else if let stage=displayRitualStage {
            let elapsed=max(0,animationClock-displayRitualStarted)
            if stage=="取香行礼" { result.gesture=artwork.gesture("incense",elapsed:elapsed,duration:2) }
            if stage=="呈出签纸" { result.gesture=artwork.gesture("paper",elapsed:elapsed,duration:2) }
            if artwork.propFrame("incense") != nil,stage=="炉烟升起" || stage=="呈出签纸" {
                let amount=stage=="呈出签纸" ? CGFloat(1):smooth(CGFloat(elapsed)/0.25)
                result.scene=SceneRitualPose(incense:amount,smoke:amount,phase:CGFloat(elapsed)+(stage=="呈出签纸" ? 2:0))
            }
        } else if let start=displayResponseStarted {
            result.gesture=artwork.gesture("response",elapsed:max(0,animationClock-start),duration:1.1)
        } else if usesServiceRoutine {
            let pose=routinePresentation.pose(at:animationClock)
            result.gesture=artwork.gesture(pose.action,elapsed:pose.frameElapsed,duration:pose.duration)
        }
        if result.gesture.prop=="fruit" {
            result.offeringFrame=shrineArtwork?.resolve(appearance:sceneAppearance,fruitStage:"fresh").freshOfferingFrame
        }
        return result
    }
    private func ceremonyDisplayPose(elapsed:TimeInterval,artwork:AttendantArtwork)->DisplayPose {
        // Keep the accepted continuous poses, played as a five-second desktop action.
        let t=CGFloat(min(16,max(0,elapsed * 3.2)))
        func ramp(_ start:CGFloat,_ end:CGFloat)->CGFloat { smooth((t-start)/(end-start)) }
        func blend(_ a:CGFloat,_ b:CGFloat,_ amount:CGFloat)->CGFloat { a+(b-a)*amount }
        let approach=ramp(0,1.5),departure=ramp(13.7,16)
        // Stop on the outer edge of the existing altar. This is the same walk
        // rig and corridor, with no new character frame or second shrine.
        let destination:CGFloat=248
        let x=blend(blend(ceremonyOrigin,destination,approach),ceremonyOrigin,departure)
        let walking=t<1.5 || t>13.7
        let direction:CGFloat=t>13.7 ? (ceremonyOrigin>=destination ? 1:-1):-1
        let distance=walking ? (t<1.5 ? abs(x-ceremonyOrigin):abs(x-destination)):0
        let placement=CeremonyPlacement(x:x,direction:direction,distance:distance,
            totalDistance:walking ? abs(ceremonyOrigin-destination):0)
        var gesture=AttendantArtwork.GesturePose.zero
        let lift=ramp(1.5,2.1),reach=ramp(5,6.4),release=ramp(6.5,7.5)
        let receive=ramp(10,10.7),paperReturn=ramp(13,13.7)
        if t<7.5 {
            gesture.nearDegrees=blend(-47,-78,reach)*lift*(1-release)
            gesture.farDegrees=22*lift*(1-release);gesture.farScale=1-0.2*lift*(1-release)
            gesture.headDegrees=(4+5*ramp(2.5,3.5)*(1-ramp(4,5)))*lift*(1-release)
            if artwork.canPresent("incense"),t<7 {
                gesture.prop="incense";gesture.propScale=lift;gesture.propAmount=lift
            }
        } else if t<10 {
            let respond=ramp(7.5,8.1)*(1-ramp(9.4,10))
            gesture.nearDegrees=(-32+3*sin((t-7.5)*4))*respond
            gesture.farDegrees=18*respond;gesture.farScale=1-0.13*respond
            gesture.headDegrees=(3+sin((t-7.5)*3))*respond
        } else {
            let amount=receive*(1-paperReturn)
            gesture.nearDegrees = -61*amount;gesture.headDegrees=2*amount
            if artwork.canPresent("paper") {
                gesture.prop="paper";gesture.propScale=amount;gesture.propAmount=amount
            }
        }
        var scene=SceneRitualPose()
        if artwork.propFrame("incense") != nil {
            scene=SceneRitualPose(incense:lift*(1-ramp(15,16)),
                smoke:ramp(6.5,7.5)*(1-ramp(14.5,16)),phase:t,handTransfer:ramp(5,7))
        }
        return DisplayPose(gesture:gesture,scene:scene,placement:placement)
    }
    private func resolvedDisplayPose()->DisplayPose {
        if let heldDisplayPose { return heldDisplayPose }
        let target=targetDisplayPose()
        if let transition=displayTransition {
            let fraction=CGFloat((animationClock-transition.started)/0.16)
            if fraction<1 {
                let from=transition.from
                var gesture=from.gesture.interpolated(to:target.gesture,fraction:fraction)
                let changedPlate=from.gesture.prop=="fruit" && target.gesture.prop=="fruit"
                    && from.offeringFrame?.image !== target.offeringFrame?.image
                if changedPlate {
                    // Changing plate artwork follows the same single-prop return
                    // as changing prop kinds; never crossfade two complete plates.
                    let amount=fraction<0.5 ? 1-fraction*2:(fraction-0.5)*2
                    let source=fraction<0.5 ? from.gesture:target.gesture
                    gesture.propScale=source.propScale*amount; gesture.propAmount=source.propAmount*amount
                }
                let frame=gesture.prop=="fruit" ? (fraction<0.5 ? from.offeringFrame:target.offeringFrame):nil
                let ambient=ambientAttendantPose()
                let rest=CeremonyPlacement(x:ambient.x,direction:ambient.direction)
                let placement: CeremonyPlacement? = from.placement == nil && target.placement == nil ? nil
                    : (from.placement ?? rest).interpolated(to:target.placement ?? rest,fraction:fraction)
                return DisplayPose(gesture:gesture,scene:from.scene.interpolated(to:target.scene,fraction:fraction),
                    offeringFrame:frame,placement:placement)
            }
        }
        return target
    }
    private func beginDisplayTransition(from previous:DisplayPose) {
        displayTransition=previous == targetDisplayPose() ? nil:(previous,animationClock)
    }
    private var routineInterrupted = false
    private var heldWalkOffsets: AttendantArtwork.WalkOffsets?
    private var walkTransition: (from: AttendantArtwork.WalkOffsets, started: TimeInterval)?
    private func targetWalkOffsets() -> AttendantArtwork.WalkOffsets? {
        let pose = attendantPose()
        return attendantArtwork?.fixedWalkOffsets(distance: pose.walk > 0 ? pose.distance : 0,
            totalDistance: pose.walk > 0 ? pose.totalDistance : 0, displayHeight: shrineArtwork?.attendantHeight ?? 170)
    }
    private func resolvedWalkOffsets() -> AttendantArtwork.WalkOffsets? {
        if resolvedDisplayPose().placement != nil { return targetWalkOffsets() }
        if routineInterrupted, let heldWalkOffsets { return heldWalkOffsets }
        guard let target = targetWalkOffsets() else { return nil }
        if let transition = walkTransition {
            let fraction = CGFloat((animationClock-transition.started)/0.16)
            if fraction < 1 { return transition.from.interpolated(to: target, fraction: fraction) }
        }
        return target
    }
    private func beginWalkTransition(from previous: AttendantArtwork.WalkOffsets?) {
        guard let previous, let next = targetWalkOffsets(), previous != next else { walkTransition = nil; return }
        walkTransition = (previous, animationClock)
    }
    private var animationClock: TimeInterval = 0
    private var routineElapsed: TimeInterval = 0
    private var responseStarted: TimeInterval?
    private var ritualStarted: TimeInterval = 0

    // The host supplies one monotonic elapsed clock. No private timer or wall-clock
    // reads: hidden rendering, hit testing and production all see the same pose.
    func updateAnimation(elapsed: TimeInterval) {
        guard elapsed.isFinite, elapsed >= animationClock else { return }
        let delta = elapsed - animationClock
        let oldClock = animationClock
        animationClock = elapsed
        // A press freezes final display parameters, not underlying clocks.
        // Responses expire even under a ritual or a held pointer.
        if let start = responseStarted {
            let finish = start + 1.1
            if elapsed >= finish {
                responseStarted = nil
                if subjectPress == nil && ceremonyElapsed == nil && ritualStage == nil && !usesServiceRoutine { routineElapsed += max(0, elapsed - max(finish, oldClock)) }
            }
        } else if subjectPress == nil && ceremonyElapsed == nil && ritualStage == nil && !usesServiceRoutine { routineElapsed += delta }
        syncRoutinePriority()
        needsDisplay = true
    }

    var insects: [[String: Any]] = [] { didSet { needsDisplay = true } }
    var offeringPlate = false { didSet { needsDisplay = true } }
    var sceneAppearance = SceneAppearance() {
        willSet { appearanceBeforeChange=newValue == sceneAppearance ? nil:resolvedDisplayPose() }
        didSet {
            if !displayPressed,let previous=appearanceBeforeChange { beginDisplayTransition(from:previous) }
            appearanceBeforeChange=nil; needsDisplay=true
        }
    }
    var appearanceAvailability: Set<String> { shrineArtwork?.availableAppearanceIDs ?? [] }
    private func selectedScene() -> ShrineArtwork.Selection? {
        let gesture=resolvedDisplayPose().gesture
        return shrineArtwork?.resolve(appearance:heldSceneAppearance ?? sceneAppearance,fruitStage:routinePresentation.snapshot?.fruitStage,
            heldBellVisible:gesture.prop=="bell" && gesture.propAmount>0.000001)
    }
    var captureMode = false { didSet { needsDisplay = true } }
    var windowMode = "passthrough"
    var persistLegacyFrame = true
    private var dragStart: NSPoint?
    private var dragCurrent: NSPoint?
    private weak var hostWindow: NSWindow?
    var emit: (([String: Any]) -> Void)?
    var constrainFrame: ((NSRect) -> NSRect)?
    private struct SubjectPress {
        let subject: String
        let screenStart: NSPoint
        let timestamp: TimeInterval
        let frame: NSRect
        var dragged = false
    }
    private var subjectPress: SubjectPress?

    // Keep the whole press, including its threshold wait, out of hit-mask polling.
    func shouldCapturePointer(at point: NSPoint) -> Bool {
        windowMode != "passthrough" || subjectPress != nil || subject(at: point) != nil
    }

    var onSubjectClick: ((String) -> Void)?
    var onSubjectMenu: ((NSEvent) -> Void)?
    var onAccessibleMenu: (() -> Void)?
    private var accessibleSubjects: [SceneAccessibleButton] = []
    // The host owns completion/skip and feeds one uninterrupted elapsed clock.
    // Assigning successive samples does not restart entry or stage transitions.
    var ceremonyElapsed: TimeInterval? {
        willSet {
            if ceremonyElapsed == nil, newValue != nil { ceremonyOrigin=attendantPose().x }
        }
        didSet {
            if let elapsed=ceremonyElapsed,!elapsed.isFinite || elapsed<0 { ceremonyElapsed=nil }
            syncRoutinePriority(); needsDisplay=true
        }
    }
    var ritualStage: String? {
        didSet {
            if ritualStage != oldValue { ritualStarted = animationClock }
            syncRoutinePriority()
            needsDisplay = true
        }
    }

    // Production PNG rendering and input share the same frame/crop/transform.
    // Vector geometry participates only when no valid production stand exists.
    func subject(at location: NSPoint) -> String? {
        let p = designPoint(location)
        // The child is drawn in front of the shrine when crossing its edge.
        if let sprites = attendantSprites() {
            if sprites.contains(where: { $0.contains(p) }) { return "attendant" }
        } else if attendantParts().contains(where: { $0.path.contains(p) }) { return "attendant" }
        if sceneIncenseSprite()?.contains(p)==true { return "shrine" }
        if let selected=selectedScene() { return selected.contains(p) ? "shrine":nil }
        func polygonContains(_ vertices: [NSPoint]) -> Bool {
            let path = NSBezierPath(); path.move(to: vertices[0])
            for vertex in vertices.dropFirst() { path.line(to: vertex) }; path.close()
            return path.contains(p)
        }
        if NSRect(x: 86, y: 190, width: 148, height: 88).contains(p)
            || polygonContains([NSPoint(x:72,y:190), NSPoint(x:160,y:144), NSPoint(x:248,y:190)])
            || polygonContains([NSPoint(x:77,y:278), NSPoint(x:243,y:278), NSPoint(x:257,y:294), NSPoint(x:63,y:294)]) { return "shrine" }
        return nil
    }
    var attendantBounds: NSRect {
        let bounds = attendantSprites()?.reduce(NSRect.null) { $0.union($1.bounds) }
            ?? attendantParts().reduce(NSRect.null) { $0.union($1.path.bounds) }
        return rect(bounds.minX, bounds.minY, bounds.width, bounds.height)
    }
    var shrineBounds: NSRect {
        var bounds = selectedScene()?.bounds ?? NSRect(x: 63, y: 144, width: 194, height: 150)
        if let incense=sceneIncenseSprite() { bounds=bounds.union(incense.bounds) }
        return rect(bounds.minX, bounds.minY, bounds.width, bounds.height)
    }
    private var cachedPlacement: (attendant: AttendantArtwork?, shrine: ShrineArtwork?, appearance: SceneAppearance, bounds: NSRect)?
    // A layout envelope is independent of the current animation frame. It uses
    // the same authored/cropped artwork and all supported poses across both
    // ends of the walking corridor, so movement never chases a moving child.
    var placementUnitBounds: NSRect {
        if let cached = cachedPlacement, cached.attendant === attendantArtwork,
           cached.shrine === shrineArtwork, cached.appearance == sceneAppearance { return cached.bounds }
        let canvas = Self.sceneCanvas
        let selection = shrineArtwork?.resolve(appearance: sceneAppearance, fruitStage: "fresh")
        var envelope = selection?.bounds ?? NSRect(x:63,y:144,width:194,height:150)
        if let artwork = attendantArtwork {
            let height = shrineArtwork?.attendantHeight ?? 170
            let stand = artwork.frame(walking:false,elapsed:0)
            let designScale = height / CGFloat(stand.height)
            var pixels: [ObjectIdentifier: NSRect] = [:]
            func alphaBounds(_ frame: AttendantArtwork.Frame) -> NSRect {
                let key = ObjectIdentifier(frame.image)
                if let cached = pixels[key] { return cached }
                var left=frame.width, top=frame.height, right = -1, bottom = -1
                for y in 0..<frame.height { for x in 0..<frame.width where frame.alpha[y*frame.width+x] > 16 {
                    left=min(left,x); top=min(top,y); right=max(right,x); bottom=max(bottom,y)
                }}
                let result = right < left ? NSRect.zero : NSRect(x:left,y:top,width:right-left+1,height:bottom-top+1)
                pixels[key] = result; return result
            }
            let poses = ["idle","sweep","read","rest","practice","offer","catch","bell","incense","paper","response"]
            for action in poses {
                for fraction in [0.0,0.125,0.25,0.375,0.5,0.625,0.75,0.875,1.0] {
                    let offsets = artwork.fixedWalkOffsets(distance:CGFloat(fraction)*73,totalDistance:73,displayHeight:height)
                    let duration = action == "catch" ? 3.0 : 4.0
                    let rendering = artwork.rendering(walking:false,elapsed:fraction*duration,offsets:offsets,
                        gesture:artwork.gesture(action,elapsed:fraction*duration,duration:duration),
                        unitToView:designScale*0.2,offeringFrame:selection?.freshOfferingFrame)
                    let scale = height / CGFloat(rendering.height)
                    for part in rendering.parts where part.fraction > 0 && part.bounds.width > 0 && part.bounds.height > 0 {
                        let source = NSRect(x:0,y:0,width:part.frame.width,height:part.frame.height)
                        let visible = alphaBounds(part.frame)
                        if visible.isEmpty { continue }
                        let placed = CGAffineTransform(a:part.bounds.width/source.width,b:0,c:0,
                            d:part.bounds.height/source.height,tx:part.bounds.minX,ty:part.bounds.minY)
                        let transformed = visible.applying(AttendantArtwork.compose(placed,part.transform))
                        for mirrored in [false,true] {
                            let facing = CGAffineTransform(a:mirrored ? -1 : 1,b:0,c:0,d:1,
                                tx:mirrored ? CGFloat(rendering.width) : 0,ty:0)
                            for x:CGFloat in [290,363] {
                                let scene = CGAffineTransform(a:scale,b:0,c:0,d:scale,
                                    tx:x-CGFloat(rendering.width)*scale/2,ty:310-height)
                                envelope = envelope.union(transformed.applying(AttendantArtwork.compose(facing,scene)))
                            }
                        }
                    }
                }
            }
        } else {
            // Stable bounds of the legacy vector child and its walking path.
            envelope = envelope.union(NSRect(x:245,y:163,width:170,height:151))
        }
        // Rendering itself clips to the scene canvas. Preserve a small raster
        // edge allowance without reinstating the entire transparent canvas.
        let clipped = envelope.insetBy(dx:-1,dy:-1).intersection(canvas)
        let unit = NSRect(x:(clipped.minX-canvas.minX)/canvas.width,
                          y:(canvas.maxY-clipped.maxY)/canvas.height,
                          width:clipped.width/canvas.width,height:clipped.height/canvas.height)
        cachedPlacement = (attendantArtwork,shrineArtwork,sceneAppearance,unit)
        return unit
    }
    var placementScreenFrame: NSRect {
        let unit = placementUnitBounds
        let local = NSRect(x:bounds.minX+unit.minX*bounds.width,y:bounds.minY+unit.minY*bounds.height,
                           width:unit.width*bounds.width,height:unit.height*bounds.height)
        let inWindow = convert(local,to:nil)
        return window?.convertToScreen(inWindow) ?? inWindow
    }
    func respond() {
        // A click under a ritual is consumed there, never queued as a later bow.
        guard ceremonyElapsed == nil && ritualStage == nil else { return }
        responseStarted = animationClock
        syncRoutinePriority()
        needsDisplay = true
    }
    override func rightMouseDown(with event: NSEvent) {
        if windowMode == "passthrough", subject(at: convert(event.locationInWindow, from: nil)) != nil { onSubjectMenu?(event) }
    }

    override func isAccessibilityElement() -> Bool { true }
    override func accessibilityRole() -> NSAccessibility.Role? { .group }
    override func accessibilityLabel() -> String? { "神龛小天地" }
    override func accessibilityChildren() -> [Any]? {
        if accessibleSubjects.isEmpty {
            for (label, subject) in [("神龛", "shrine"), ("道童", "attendant"), ("场景菜单", "menu")] {
                let element = SceneAccessibleButton()
                element.setAccessibilityRole(.button); element.setAccessibilityLabel(label); element.setAccessibilityEnabled(true)
                element.setAccessibilityParent(self)
                element.press = { [weak self] in
                    if subject == "menu" { self?.onAccessibleMenu?() } else { self?.onSubjectClick?(subject) }
                }
                element.showMenu = { [weak self] in self?.onAccessibleMenu?() }
                accessibleSubjects.append(element)
            }
        }
        for (index, frame) in [shrineBounds, attendantBounds, shrineBounds].enumerated() {
            let inWindow = convert(frame, to: nil)
            accessibleSubjects[index].setAccessibilityFrame(window?.convertToScreen(inWindow) ?? inWindow)
        }
        return accessibleSubjects
    }

    override var isOpaque: Bool { false }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    func cancelInteraction() {
        if let press = subjectPress, press.dragged { hostWindow?.setFrame(press.frame, display: true) }
        subjectPress = nil; dragStart = nil; dragCurrent = nil
        syncRoutinePriority()
        setClickThroughAfterInteraction()
        needsDisplay = true
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 {
            cancelInteraction()
        } else {
            super.keyDown(with: event)
        }
    }

    func attach(window: NSWindow) {
        hostWindow = window
        NotificationCenter.default.addObserver(self, selector: #selector(cancelOnFocusLoss),
                                               name: NSWindow.didResignKeyNotification, object: window)
        NotificationCenter.default.addObserver(self, selector: #selector(cancelOnFocusLoss),
                                               name: NSApplication.didResignActiveNotification, object: nil)
    }

    @objc private func cancelOnFocusLoss(_ notification: Notification) {
        guard windowMode != "passthrough" || subjectPress != nil else { return }
        cancelInteraction()
    }

    private var scaleFactor: CGFloat { max(0.0001, min(bounds.width / Self.sceneCanvas.width, bounds.height / Self.sceneCanvas.height)) }
    private func designPoint(_ point: NSPoint) -> NSPoint {
        let s = scaleFactor
        let left = (bounds.width - Self.sceneCanvas.width * s) / 2
        let top = (bounds.height - Self.sceneCanvas.height * s) / 2
        return NSPoint(x: Self.sceneCanvas.minX + (point.x - bounds.minX - left) / s,
                       y: Self.sceneCanvas.minY + (bounds.maxY - point.y - top) / s)
    }
    private func point(_ x: CGFloat, _ y: CGFloat) -> NSPoint {
        let s = scaleFactor
        let left = (bounds.width - Self.sceneCanvas.width * s) / 2
        let top = (bounds.height - Self.sceneCanvas.height * s) / 2
        return NSPoint(x: bounds.minX + left + (x - Self.sceneCanvas.minX) * s, y: bounds.maxY - top - (y - Self.sceneCanvas.minY) * s)
    }
    private func rect(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) -> NSRect {
        let a = point(x, y + h), b = point(x + w, y)
        return NSRect(x: a.x, y: a.y, width: b.x - a.x, height: b.y - a.y)
    }
    private func polygon(_ coords: [(CGFloat, CGFloat)], fill: NSColor, stroke: NSColor? = nil, line: CGFloat = 1) {
        let path = NSBezierPath()
        for (index, xy) in coords.enumerated() {
            let p = point(xy.0, xy.1)
            if index == 0 { path.move(to: p) } else { path.line(to: p) }
        }
        path.close()
        fill.setFill(); path.fill()
        if let stroke = stroke { stroke.setStroke(); path.lineWidth = line * scaleFactor; path.stroke() }
    }
    private func ellipse(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat, fill: NSColor, stroke: NSColor? = nil, line: CGFloat = 1) {
        let path = NSBezierPath(ovalIn: rect(x, y, w, h))
        fill.setFill(); path.fill()
        if let stroke = stroke { stroke.setStroke(); path.lineWidth = line * scaleFactor; path.stroke() }
    }
    private func line(_ points: [(CGFloat, CGFloat)], color: NSColor, width: CGFloat = 2) {
        let path = NSBezierPath()
        for (index, xy) in points.enumerated() {
            let p = point(xy.0, xy.1)
            if index == 0 { path.move(to: p) } else { path.line(to: p) }
        }
        color.setStroke(); path.lineWidth = width * scaleFactor; path.lineCapStyle = .round; path.stroke()
    }
    private func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat, _ alpha: CGFloat = 1) -> NSColor {
        NSColor(calibratedRed: red, green: green, blue: blue, alpha: alpha)
    }

    override func draw(_ dirtyRect: NSRect) {
        (previewBackgroundColor ?? NSColor.clear).setFill(); dirtyRect.fill(using: .copy)
        drawShrine()
        drawAttendant()
        if let transfer=resolvedDisplayPose().scene.handTransfer,transfer<1,
           let incense=sceneIncenseSprite() { incense.draw(designToView:designToViewTransform) }
        drawRitualSmoke()
        if attendantArtwork == nil && (ritualStage == "炉烟升起" || ritualStage == "呈出签纸") {
            line([(160, 266), (160, 247)], color: color(0.54, 0.28, 0.15), width: 2)
            line([(160, 247), (154, 234), (164, 219), (159, 208)], color: color(0.84, 0.81, 0.74, 0.65), width: 2)
        }
        if let start = dragStart, let current = dragCurrent, captureMode {
            let a = designPoint(start), b = designPoint(current)
            let box = rect(min(a.x, b.x), min(a.y, b.y), abs(b.x - a.x), abs(b.y - a.y))
            let path = NSBezierPath(rect: box)
            color(0.74, 0.22, 0.22, 0.15).setFill(); path.fill()
            color(0.80, 0.18, 0.18, 0.92).setStroke(); path.lineWidth = max(2, 2 * scaleFactor); path.stroke()
        }
    }

    private func drawShrine() {
        if let selected=selectedScene() {
            for layer in selected.layers {
                let transfer=resolvedDisplayPose().scene.handTransfer
                if layer.id=="incense",transfer == nil,
                   let incense=sceneIncenseSprite() { incense.draw(designToView:designToViewTransform) }
                layer.frame.draw(in: rect(layer.bounds.minX, layer.bounds.minY, layer.bounds.width, layer.bounds.height), mirrored: false)
                // The authored censer mouth sits inside its opaque raster.
                // Place the carried incense at that mouth after its own layer,
                // retaining the legacy fixture order for legacy ritualStage.
                if layer.id=="incense",transfer == 1,
                   let incense=sceneIncenseSprite() { incense.draw(designToView:designToViewTransform) }
            }
            return
        }
        let wood = color(0.42, 0.31, 0.22, 0.96)
        let dark = color(0.20, 0.16, 0.13, 0.98)
        let gold = color(0.82, 0.70, 0.49, 0.98)
        let earth = color(0.62, 0.51, 0.38, 0.95)
        polygon([(72, 190), (160, 144), (248, 190)], fill: wood, stroke: dark, line: 3)
        polygon([(86, 190), (234, 190), (234, 278), (86, 278)], fill: earth, stroke: dark, line: 3)
        polygon([(100, 207), (220, 207), (220, 256), (100, 256)], fill: dark, stroke: gold, line: 2)
        // Six arms of the static idol.
        for (dx, dy) in [(-46, 5), (-56, 21), (-45, 38), (46, 5), (56, 21), (45, 38)] {
            line([(160, 218), (CGFloat(160 + dx), CGFloat(218 + dy))], color: gold, width: 3)
        }
        ellipse(146, 203, 28, 30, fill: gold, stroke: dark, line: 2)
        polygon([(77, 278), (243, 278), (257, 294), (63, 294)], fill: wood, stroke: dark, line: 2)
        ellipse(143, 275, 34, 10, fill: color(0.55, 0.43, 0.29, 0.98), stroke: gold)
        let fruit: NSColor
        switch routinePresentation.snapshot?.fruitStage {
        case "fresh": fruit = color(0.70, 0.30, 0.21)
        case "ripe": fruit = color(0.57, 0.23, 0.18)
        default: fruit = color(0.67, 0.26, 0.19)
        }
        for x in [148.0, 160.0, 172.0] { ellipse(x, 270, 7, 7, fill: fruit) }
        if offeringPlate {
            ellipse(181, 260, 22, 8, fill: color(0.86, 0.76, 0.58), stroke: gold)
            ellipse(186, 256, 12, 5, fill: color(0.70, 0.22, 0.18), stroke: gold, line: 0.7)
        }
    }

    private struct AttendantPose {
        var x: CGFloat = 355
        var direction: CGFloat = -1
        var distance: CGFloat = 0
        var totalDistance: CGFloat = 0
        var walk: CGFloat = 0
        var sweep: CGFloat = 0
        var rest: CGFloat = 0
        var bow: CGFloat = 0
        var frameElapsed: TimeInterval?
    }
    private func smooth(_ value: CGFloat) -> CGFloat {
        let x = min(1, max(0, value)); return x * x * (3 - 2 * x)
    }
    private func attendantPose() -> AttendantPose {
        var pose=ambientAttendantPose()
        if let placement=resolvedDisplayPose().placement {
            pose.x=placement.x; pose.direction=placement.direction
            pose.distance=placement.distance; pose.totalDistance=placement.totalDistance
            pose.walk=placement.totalDistance>0 ? 1:0; pose.sweep=0; pose.rest=0
        }
        return pose
    }
    private func ambientAttendantPose() -> AttendantPose {
        if !usesServiceRoutine,let heldLegacyPose { return heldLegacyPose }
        if usesServiceRoutine {
            let current = routinePresentation.pose(at: animationClock)
            var pose = AttendantPose()
            pose.x = current.x; pose.direction = current.direction
            pose.distance = current.travelDistance; pose.totalDistance = current.totalDistance
            pose.walk = current.walking ? 1 : 0; pose.frameElapsed = current.frameElapsed
            return pose
        }
        // Only old, explicitly service-free fixtures use the temporary loop.
        let t = routineElapsed.truncatingRemainder(dividingBy: 26)
        var pose = AttendantPose()
        func walk(_ start: Double, _ duration: Double, _ from: CGFloat, _ to: CGFloat) {
            let progress = CGFloat((t - start) / duration)
            pose.x = from + (to - from) * smooth(progress)
            pose.direction = to >= from ? 1 : -1
            pose.distance = abs(pose.x - from)
            pose.totalDistance = abs(to-from)
            pose.walk = smooth(min(CGFloat(t - start) / 0.25, CGFloat(start + duration - t) / 0.25))
        }
        switch t {
        case 3..<8: walk(3, 5, 355, 290)
        case 8..<11:
            pose.x = 290
            pose.sweep = smooth(min(CGFloat(t - 8) / 0.3, CGFloat(11 - t) / 0.3))
        case 11..<17: walk(11, 6, 290, 363)
        case 17..<21:
            pose.x = 363
            pose.rest = smooth(min(CGFloat(t - 17) / 0.5, CGFloat(21 - t) / 0.5))
        case 21..<22: walk(21, 1, 363, 355)
        default: break
        }
        if let start = responseStarted {
            pose.bow = CGFloat(sin(min(1, max(0, (animationClock - start) / 1.1)) * .pi))
            // Settle the feet and sleeves before the bow, at the current position.
            pose.walk *= 1 - pose.bow
            pose.sweep *= 1 - pose.bow
            pose.rest *= 1 - pose.bow
        } else if ritualStage == "取香行礼" {
            pose.bow = smooth(CGFloat(animationClock - ritualStarted) / 0.4)
            pose.walk = 0; pose.sweep = 0; pose.rest = 0
        }
        return pose
    }
    private struct AttendantPart {
        let path: NSBezierPath
        let fill: NSColor
        var stroke: NSColor? = nil
        var width: CGFloat = 1
    }
    private func attendantParts() -> [AttendantPart] {
        let pose = attendantPose()
        let x = pose.x, y: CGFloat = 262
        // PROGRAM-DRAWN TEMPORARY ART. Same identity across every activity;
        // replace only after the standalone A01 animation passes edge review.
        let skin = color(0.32, 0.30, 0.35), skinLight = color(0.40, 0.37, 0.41)
        let robe = color(0.12, 0.115, 0.14), sleeve = color(0.16, 0.15, 0.18)
        let ink = color(0.065, 0.055, 0.075), white = color(0.94, 0.93, 0.89)
        let hairLine = color(0.76, 0.76, 0.74), red = color(0.70, 0.22, 0.27)
        let phase = pose.distance / 18 * 2 * .pi
        let gait = sin(phase) * pose.walk
        let breath = CGFloat(sin(routineElapsed * .pi / 2)) * 0.7 * (1 - pose.walk)
        let upperDrop = pose.rest * 9 + pose.bow * 8 - breath - abs(gait) * 0.65
        let headDrop = upperDrop + pose.bow * 5
        var parts: [AttendantPart] = []
        func poly(_ coords: [(CGFloat, CGFloat)], _ fill: NSColor, _ stroke: NSColor? = nil, _ width: CGFloat = 1) {
            let path = NSBezierPath()
            for (index, xy) in coords.enumerated() {
                let p = NSPoint(x:x + xy.0, y:y + xy.1)
                if index == 0 { path.move(to:p) } else { path.line(to:p) }
            }
            path.close(); parts.append(AttendantPart(path:path, fill:fill, stroke:stroke, width:width))
        }
        func oval(_ dx: CGFloat, _ dy: CGFloat, _ w: CGFloat, _ h: CGFloat, _ fill: NSColor, _ stroke: NSColor? = nil, _ width: CGFloat = 1) {
            parts.append(AttendantPart(path:NSBezierPath(ovalIn:NSRect(x:x+dx,y:y+dy,width:w,height:h)),fill:fill,stroke:stroke,width:width))
        }
        // A stance foot moves backward relative to the body at the same speed
        // that the body advances; the alternating swing foot rises and returns.
        for (side, offset) in [(-1.0, 0.0), (1.0, 0.5)] {
            let cycle = (Double(pose.distance / 18) + offset).truncatingRemainder(dividingBy:1)
            let footTravel = CGFloat(cycle < 0.5 ? 0.25-cycle : cycle-0.75) * 18 * pose.walk * pose.direction
            let lift = cycle < 0.5 ? 0 : CGFloat(sin((cycle-0.5) * 2 * .pi)) * 5 * pose.walk
            let footX = CGFloat(side) * (10 + pose.rest * 4) + footTravel
            poly([(CGFloat(side)*7,26),(footX+4,45-lift),(footX-4,45-lift),(CGFloat(side)*7-5,27)],robe)
            oval(footX-9,42-lift,19,8,robe,ink,1)
        }
        // Broad, plain robe, with a hem that follows the alternating steps.
        poly([(-23,-48+upperDrop),(23,-48+upperDrop),(32,7),(37+gait*1.5,30),(-37+gait*1.5,30),(-32,7)],robe,ink,1.3)
        poly([(-11,-46+upperDrop),(0,-34+upperDrop),(11,-46+upperDrop),(17,-29+upperDrop),(0,-15+upperDrop),(-17,-29+upperDrop)],white)
        poly([(0,-34+upperDrop),(12,-46+upperDrop),(24,-38+upperDrop),(10,-9),(-2,-14)],robe)
        // Sleeves move opposite their foot. Hands join for a respectful bow.
        for side in [-1.0,1.0] {
            let sign = CGFloat(side)
            let armSwing = -sign * gait * 5
            let wristX = sign * (25 - pose.bow * 20 - pose.rest * 14)
            let wristY = 4 + armSwing - pose.bow * 11 + pose.rest * 3
            poly([(sign*20,-40+upperDrop),(sign*31,-31+upperDrop),(wristX+sign*8,wristY+5),(wristX-sign*8,wristY+3),(sign*14,-20+upperDrop)],sleeve,ink,1)
            oval(wristX-4,wristY-1,8,9,skin)
        }
        poly([(-28,-11),(28,-11),(28,-5),(-28,-5)],color(0.40,0.37,0.34))
        poly([(-2,-5),(3,-5),(4,13),(-1,13)],color(0.40,0.37,0.34))
        // Both ear roots overlap the cheek in a full vertical band. Ear tips
        // point outwards; neither ear is a separate floating triangle.
        for side in [-1.0,1.0] {
            let sign = CGFloat(side)
            poly([(sign*22,-85+headDrop),(sign*52,-95+headDrop),(sign*38,-67+headDrop),(sign*22,-65+headDrop)],skin,ink,1.1)
            poly([(sign*27,-81+headDrop),(sign*44,-90+headDrop),(sign*32,-71+headDrop)],skinLight)
        }
        oval(-29,-105+headDrop,58,59-pose.bow*3,skin,ink,1.3)
        // Curved swept-back cap leaves the central forehead bare; one white bun.
        let hair = NSBezierPath()
        hair.move(to:NSPoint(x:x-28,y:y-88+headDrop))
        hair.curve(to:NSPoint(x:x-23,y:y-108+headDrop),controlPoint1:NSPoint(x:x-30,y:y-99+headDrop),controlPoint2:NSPoint(x:x-27,y:y-104+headDrop))
        hair.curve(to:NSPoint(x:x+23,y:y-108+headDrop),controlPoint1:NSPoint(x:x-11,y:y-118+headDrop),controlPoint2:NSPoint(x:x+12,y:y-118+headDrop))
        hair.curve(to:NSPoint(x:x+28,y:y-88+headDrop),controlPoint1:NSPoint(x:x+28,y:y-103+headDrop),controlPoint2:NSPoint(x:x+30,y:y-97+headDrop))
        hair.curve(to:NSPoint(x:x,y:y-100+headDrop),controlPoint1:NSPoint(x:x+22,y:y-97+headDrop),controlPoint2:NSPoint(x:x+15,y:y-101+headDrop))
        hair.curve(to:NSPoint(x:x-28,y:y-88+headDrop),controlPoint1:NSPoint(x:x-15,y:y-101+headDrop),controlPoint2:NSPoint(x:x-22,y:y-97+headDrop))
        hair.close(); parts.append(AttendantPart(path:hair,fill:white,stroke:hairLine,width:0.8))
        oval(-9,-124+headDrop,18,17,white,hairLine,0.8)
        let blinkPhase = routineElapsed.truncatingRemainder(dividingBy:4.3)
        let blink = blinkPhase >= 2.2 && blinkPhase < 2.34
        let eyesClosed = blink || pose.bow > 0.6 || pose.rest > 0.8
        for side in [-1.0,1.0] {
            let eyeX = CGFloat(side)*11 - 3
            oval(eyeX,-79+headDrop,7,eyesClosed ? 1.4 : 7.5,eyesClosed ? ink : red)
            if !eyesClosed { oval(eyeX+2.4,-77+headDrop,2.2,4.2,ink); oval(eyeX+1.4,-78+headDrop,1.4,1.4,white) }
        }
        oval(-2.5,-62+headDrop,5,1.3,ink)
        if pose.sweep > 0 {
            let sweep = sin(CGFloat(routineElapsed) * 4) * 7 * pose.sweep
            let topX: CGFloat = -18, bottomX: CGFloat = -39+sweep
            // The small broom is a daily action prop; its filled parts also hit.
            poly([(topX-1,-1),(topX+1,-1),(bottomX+1,38),(bottomX-1,38)],color(0.49,0.37,0.24))
            poly([(bottomX-3,32),(bottomX+3,32),(bottomX+11,46),(bottomX-10,46)],color(0.64,0.53,0.35))
        }
        return parts
    }
    private struct MappedSprite {
        let frame:AttendantArtwork.Frame
        let pixelToDesign:CGAffineTransform
        let fraction:CGFloat
        var bounds:NSRect { NSRect(x:0,y:0,width:frame.width,height:frame.height).applying(pixelToDesign) }
        func contains(_ point:NSPoint) -> Bool {
            let determinant=pixelToDesign.a*pixelToDesign.d-pixelToDesign.b*pixelToDesign.c
            guard determinant.isFinite,abs(determinant)>0.00000001,fraction>0 else { return false }
            let p=point.applying(pixelToDesign.inverted())
            guard p.x.isFinite,p.y.isFinite,p.x>=0,p.y>=0,
                  p.x<CGFloat(frame.width),p.y<CGFloat(frame.height) else { return false }
            return CGFloat(frame.alpha[Int(p.y)*frame.width+Int(p.x)])*fraction>16
        }
        func draw(designToView:CGAffineTransform) {
            guard fraction>0,let context=NSGraphicsContext.current?.cgContext else { return }
            var box=NSRect(x:0,y:0,width:frame.width,height:frame.height)
            guard let image=frame.image.cgImage(forProposedRect:&box,context:nil,hints:nil) else { return }
            context.saveGState()
            context.concatenate(AttendantArtwork.compose(pixelToDesign,designToView))
            context.translateBy(x:0,y:CGFloat(frame.height)); context.scaleBy(x:1,y:-1)
            switch frame.interpolation {
            case .none:context.interpolationQuality = .none
            case .low:context.interpolationQuality = .low
            case .medium:context.interpolationQuality = .medium
            default:context.interpolationQuality = .high
            }
            context.setAlpha(fraction); context.draw(image,in:box)
            context.restoreGState()
        }
    }
    private var designToViewTransform:CGAffineTransform {
        let origin=point(0,0),s=scaleFactor
        return CGAffineTransform(a:s,b:0,c:0,d:-s,tx:origin.x,ty:origin.y)
    }
    private var ritualAnchor:NSPoint? {
        selectedScene()?.incenseAnchor
    }
    private func sceneIncenseSprite()->MappedSprite? {
        let pose=resolvedDisplayPose().scene
        guard pose.incense>0.000001,let anchor=ritualAnchor,let artwork=attendantArtwork,
              let frame=artwork.propFrame("incense"),let core=artwork.propCoreBounds("incense"),
              let width=artwork.propWidth("incense",height:18,unitToView:scaleFactor*(pose.handTransfer == nil ? 1:0.6)) else { return nil }
        let sx=width/CGFloat(frame.width),sy=CGFloat(18)/CGFloat(frame.height)
        var target=CGAffineTransform(a:sx,b:0,c:0,d:sy,
            tx:anchor.x-core.midX*sx,ty:anchor.y-core.maxY*sy)
        if let transfer=pose.handTransfer {
            let display=resolvedDisplayPose()
            var held=display.gesture
            held.prop="incense";held.propScale=1;held.propAmount=1
            let height=shrineArtwork?.attendantHeight ?? 170
            let stand=artwork.frame(walking:false,elapsed:0)
            let rendering=artwork.rendering(walking:false,elapsed:0,offsets:nil,gesture:held,
                unitToView:height/CGFloat(stand.height)*scaleFactor)
            if let source=mappedSprites(rendering,pose:attendantPose(),height:height).first(where:{$0.frame.image === frame.image}) {
                let a=source.pixelToDesign
                // Keep source handedness while straightening the thin original
                // incense, so matrix interpolation never collapses its width.
                if a.a*a.d-a.b*a.c<0 {
                    target.a = -sx;target.tx=anchor.x+core.midX*sx
                }
                func blend(_ from:CGFloat,_ to:CGFloat)->CGFloat { from+(to-from)*transfer }
                target=CGAffineTransform(a:blend(a.a,target.a),b:blend(a.b,target.b),
                    c:blend(a.c,target.c),d:blend(a.d,target.d),tx:blend(a.tx,target.tx),ty:blend(a.ty,target.ty))
            }
        }
        return MappedSprite(frame:frame,pixelToDesign:target,fraction:pose.incense)
    }
    private func drawRitualSmoke() {
        let pose=resolvedDisplayPose().scene
        guard pose.smoke>0.000001,let anchor=ritualAnchor,let incense=sceneIncenseSprite() else { return }
        var tip=NSPoint(x:anchor.x,y:incense.bounds.minY)
        if pose.handTransfer != nil,let core=attendantArtwork?.propCoreBounds("incense") {
            tip=NSPoint(x:core.midX,y:core.minY).applying(incense.pixelToDesign)
        }
        let x=tip.x,y=tip.y,phase=pose.phase
        let path=[(x,y),(x+sin(phase*1.4)*1.3,y-5),
                  (x-1.5+sin(phase*1.4+0.8),y-11),(x+sin(phase*1.4+1.4)*1.7,y-18)]
        // One short smoke path, with a quiet edge that survives light/dark art.
        line(path,color:color(0.20,0.20,0.19,0.34*pose.smoke),width:max(1.6,1.4/scaleFactor))
        line(path,color:color(0.91,0.91,0.87,0.72*pose.smoke),width:max(0.8,0.75/scaleFactor))
    }
    private func attendantSprites() -> [MappedSprite]? {
        guard let artwork = attendantArtwork else { return nil }
        let pose = attendantPose()
        let height: CGFloat = shrineArtwork?.attendantHeight ?? 170
        let sourceHeight=CGFloat(artwork.frame(walking:false,elapsed:0).height)
        let display=resolvedDisplayPose()
        let rendering = artwork.rendering(walking: pose.walk > 0, elapsed: pose.frameElapsed ?? routineElapsed,
            offsets:resolvedWalkOffsets(),gesture:display.gesture,unitToView:height/sourceHeight*scaleFactor,
            offeringFrame:display.offeringFrame)
        let carried=display.scene.handTransfer != nil && display.scene.incense>0 ? artwork.propFrame("incense")?.image:nil
        return mappedSprites(rendering,pose:pose,height:height).filter { $0.frame.image !== carried }
    }
    private func mappedSprites(_ rendering:AttendantArtwork.Rendering,pose:AttendantPose,height:CGFloat)->[MappedSprite] {
        let scale = height/CGFloat(rendering.height)
        let width = scale*CGFloat(rendering.width)
        let bounds = NSRect(x: pose.x - width / 2, y: 310 - height, width: width, height: height)
        return rendering.parts.filter { $0.fraction>0 && $0.bounds.width>0 && $0.bounds.height>0 }.map { part in
            let mirrored = (pose.direction < 0) != part.frame.facesLeft
            let placed=CGAffineTransform(a:part.bounds.width/CGFloat(part.frame.width),b:0,c:0,
                d:part.bounds.height/CGFloat(part.frame.height),tx:part.bounds.minX,ty:part.bounds.minY)
            let source=AttendantArtwork.compose(placed,part.transform)
            let facing=CGAffineTransform(a:mirrored ? -1 : 1,b:0,c:0,d:1,tx:mirrored ? CGFloat(rendering.width) : 0,ty:0)
            let scene=CGAffineTransform(a:scale,b:0,c:0,d:scale,tx:bounds.minX,ty:bounds.minY)
            return MappedSprite(frame:part.frame,pixelToDesign:AttendantArtwork.compose(AttendantArtwork.compose(source,facing),scene),fraction:part.fraction)
        }
    }
    private func drawAttendant() {
        if let sprites = attendantSprites() {
            for sprite in sprites {
                sprite.draw(designToView:designToViewTransform)
            }
            return
        }
        let s = scaleFactor
        let origin = point(0,0)
        let transform = AffineTransform(m11:s,m12:0,m21:0,m22:-s,tX:origin.x,tY:origin.y)
        for part in attendantParts() {
            let path = part.path.copy() as! NSBezierPath
            path.transform(using:transform)
            part.fill.setFill(); path.fill()
            if let stroke = part.stroke {
                stroke.setStroke(); path.lineWidth = part.width*s; path.stroke()
            }
        }
    }

    private func drawInsects() {
        for (index, bug) in insects.enumerated() {
            guard let id = bug["id"] as? String,
                  let nx = bug["x"] as? CGFloat,
                  let ny = bug["y"] as? CGFloat,
                  let colorName = bug["color"] as? String else { continue }
            let phase = ProcessInfo.processInfo.systemUptime + Double(index) * 2.3
            let x = 36 + nx * 468 + CGFloat(sin(phase * 1.2) * 5)
            let y = 34 + ny * 290 + CGFloat(cos(phase) * 4)
            let fill: NSColor
            switch colorName {
            case "中褐色": fill = color(0.72, 0.52, 0.34)
            case "深褐色": fill = color(0.31, 0.26, 0.24)
            case "白色": fill = color(0.94, 0.91, 0.83)
            default: fill = color(0.61, 0.39, 0.25)
            }
            ellipse(x-7,y-5,14,10,fill:fill,stroke:color(0.35,0.29,0.23,0.88),line:1)
            ellipse(x-2.5,y-1,2,2,fill:color(0.12,0.10,0.08))
            line([(x+4,y-1),(x+9,y-5)],color:color(0.36,0.30,0.23),width:1)
            _ = id
        }
    }

    override func mouseDown(with event: NSEvent) {
        let location = convert(event.locationInWindow, from: nil)
        if windowMode == "passthrough", let subject = subject(at: location) {
            if event.modifierFlags.contains(.control) { onSubjectMenu?(event) }
            else {
                subjectPress = SubjectPress(subject: subject, screenStart: screenLocation(event),
                                            timestamp: event.timestamp, frame: hostWindow?.frame ?? .zero)
                syncRoutinePriority()
                hostWindow?.ignoresMouseEvents = false
            }
            return
        }
        if windowMode == "capture" {
            dragStart = location; dragCurrent = location; needsDisplay = true
        } else if windowMode == "move" || windowMode == "resize" {
            dragStart = location; dragCurrent = location
        }
    }
    override func mouseDragged(with event: NSEvent) {
        if subjectPress != nil { updateSubjectDrag(screenLocation(event)); return }
        let location = convert(event.locationInWindow, from: nil)
        dragCurrent = location
        if windowMode == "move", let start = dragStart, let window = hostWindow {
            let delta = NSPoint(x: location.x - start.x, y: location.y - start.y)
            window.setFrameOrigin(NSPoint(x: window.frame.origin.x + delta.x, y: window.frame.origin.y + delta.y))
        } else if windowMode == "resize", let start = dragStart, let window = hostWindow {
            let delta = NSPoint(x: location.x - start.x, y: location.y - start.y)
            var frame = window.frame
            frame.size.width = max(360, frame.size.width + delta.x)
            frame.size.height = max(250, frame.size.height + delta.y)
            window.setFrame(constrainFrame?(frame) ?? frame, display: true)
            dragStart = location
        }
        needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) {
        if subjectPress != nil {
            updateSubjectDrag(screenLocation(event))
            let press = subjectPress!
            subjectPress = nil
            hostWindow?.ignoresMouseEvents = true
            if press.dragged { emitWindowFrame() }
            else if event.timestamp >= press.timestamp && event.timestamp - press.timestamp <= 0.5 {
                onSubjectClick?(press.subject)
            }
            syncRoutinePriority()
            return
        }
        let location = convert(event.locationInWindow, from: nil)
        if windowMode == "capture", let start = dragStart {
            let a = designPoint(start), b = designPoint(location)
            let x1 = a.x, y1 = a.y, x2 = b.x, y2 = b.y
            let left = min(x1, x2), right = max(x1, x2)
            let top = min(y1, y2), bottom = max(y1, y2)
            var ids: [String] = []
            for bug in insects {
                guard let id = bug["id"] as? String,
                      let nx = bug["x"] as? CGFloat,
                      let ny = bug["y"] as? CGFloat else { continue }
                let bx = 36 + nx * 468, by = 34 + ny * 290
                if bx >= left && bx <= right && by >= top && by <= bottom { ids.append(id) }
            }
            emit?(["type": "capture", "ids": ids])
            setClickThroughAfterInteraction()
        } else if windowMode == "move" || windowMode == "resize" {
            if let window = hostWindow {
                if persistLegacyFrame { UserDefaults.standard.set(["x": window.frame.origin.x, "y": window.frame.origin.y,
                                           "width": window.frame.width, "height": window.frame.height],
                                          forKey: "overlayFrame") }
                emit?(["type": "window_frame", "x": window.frame.origin.x, "y": window.frame.origin.y,
                       "width": window.frame.width, "height": window.frame.height])
            setClickThroughAfterInteraction()
        }
        }
        dragStart = nil; dragCurrent = nil
        needsDisplay = true
    }

    private func screenLocation(_ event: NSEvent) -> NSPoint {
        hostWindow?.convertPoint(toScreen: event.locationInWindow) ?? event.locationInWindow
    }

    private func updateSubjectDrag(_ point: NSPoint) {
        guard var press = subjectPress else { return }
        let dx = point.x - press.screenStart.x, dy = point.y - press.screenStart.y
        press.dragged = press.dragged || hypot(dx, dy) >= 6
        subjectPress = press
        if press.dragged, let window = hostWindow {
            let proposed = press.frame.offsetBy(dx: dx, dy: dy)
            window.setFrame(constrainFrame?(proposed) ?? proposed, display: true)
        }
    }

    private func emitWindowFrame() {
        guard let frame = hostWindow?.frame else { return }
        if persistLegacyFrame {
            UserDefaults.standard.set(["x":frame.minX, "y":frame.minY, "width":frame.width, "height":frame.height], forKey:"overlayFrame")
        }
        emit?(["type":"window_frame", "x":frame.minX, "y":frame.minY, "width":frame.width, "height":frame.height])
    }

    private func setClickThroughAfterInteraction() {
        windowMode = "passthrough"
        captureMode = false
        hostWindow?.ignoresMouseEvents = true
        emit?(["type": "mode", "mode": "passthrough"])
    }
}

final class OverlayWindow: NSWindow {
    override var canBecomeKey: Bool { true }
}

final class Host: NSObject, NSApplicationDelegate {
    private var window: OverlayWindow!
    private var view: TianmuView!
    private var statusItem: NSStatusItem!
    private var mode = "passthrough"
    private var returnApplication: NSRunningApplication?
    private let outputLock = NSLock()

    func emit(_ value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed]),
              let text = String(data: data, encoding: .utf8) else { return }
        outputLock.lock(); print(text); fflush(stdout); outputLock.unlock()
    }
    func send(_ type: String, _ values: [String: Any] = [:]) { var item = values; item["type"] = type; emit(item) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        createOverlay()
        createStatusMenu()
        send("ready", ["frame": ["x": window.frame.origin.x, "y": window.frame.origin.y,
                                "width": window.frame.width, "height": window.frame.height]])
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            while let line = readLine() {
                guard let data = line.data(using: .utf8),
                      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
                DispatchQueue.main.async { self?.handle(object) }
            }
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
        if CommandLine.arguments.contains("--smoke-test") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { NSApp.terminate(nil) }
        }
    }
    private func createOverlay() {
        let frame = NSRect(x: 140, y: 90, width: 540, height: 380)
        window = OverlayWindow(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.backgroundColor = .clear; window.isOpaque = false; window.hasShadow = false
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        window.ignoresMouseEvents = true
        view = TianmuView(frame: NSRect(origin: .zero, size: frame.size))
        view.attach(window: window)
        view.emit = { [weak self] event in
            if event["type"] as? String == "mode", let next = event["mode"] as? String {
                self?.mode = next
                if next == "passthrough" {
                    // The user already chose another app on focus loss; never steal it back.
                    if event["reason"] as? String == "focus_lost" { self?.returnApplication = nil }
                    else { self?.restorePreviousApplication() }
                }
            }
            self?.emit(event)
        }
        window.contentView = view
        if let saved = UserDefaults.standard.dictionary(forKey: "overlayFrame"),
           let x = saved["x"] as? CGFloat, let y = saved["y"] as? CGFloat,
           let width = saved["width"] as? CGFloat, let height = saved["height"] as? CGFloat,
           width >= 360, height >= 250 {
            window.setFrame(NSRect(x: x, y: y, width: width, height: height), display: false)
            view.setFrameSize(NSSize(width: width, height: height))
        }
        window.orderFrontRegardless()
    }
    private func createStatusMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "天姥"
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "打开控制面板", action: #selector(showPanel), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "开始拉网捕虫", action: #selector(toggleCapture), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "移动桌角小庙", action: #selector(enableMove), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "调整桌角大小", action: #selector(enableResize), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "隐藏桌角小庙", action: #selector(hideOverlay), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "显示桌角小庙", action: #selector(showOverlay), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "清除计时提醒", action: #selector(clearTimerReminder), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "退出天姥", action: #selector(quit), keyEquivalent: "q"))
        for item in menu.items { item.target = self }
        statusItem.menu = menu
    }
    @objc private func showPanel() {
        setMode("passthrough")
        window.orderOut(nil)
        send("overlay_visibility", ["visible": false])
        send("show_panel")
    }
    @objc private func hideOverlay() {
        setMode("passthrough")
        window.orderOut(nil)
        send("overlay_visibility", ["visible": false, "requested_visible": false])
    }
    @objc private func showOverlay() {
        setMode("passthrough")
        window.orderFrontRegardless()
        send("overlay_visibility", ["visible": true, "requested_visible": true])
    }
    @objc private func toggleCapture() {
        if mode == "capture" { setMode("passthrough") } else { setMode("capture"); send("capture_mode", ["enabled": true]) }
    }
    @objc private func enableMove() { NSApp.activate(ignoringOtherApps: true); setMode("move") }
    @objc private func enableResize() { NSApp.activate(ignoringOtherApps: true); setMode("resize") }
    @objc private func clearTimerReminder() { statusItem.button?.title = "天姥"; send("timer_dismissed") }
    @objc private func quit() { send("quit"); NSApp.terminate(nil) }
    private func setMode(_ next: String) {
        if next == "capture" || next == "move" || next == "resize" {
            rememberFrontmostApplication()
        }
        mode = next
        view.windowMode = next
        view.captureMode = next == "capture"
        window.ignoresMouseEvents = next == "passthrough"
        if next == "capture" || next == "move" || next == "resize" {
            window.makeKeyAndOrderFront(nil)
            window.makeFirstResponder(view)
        } else {
            restorePreviousApplication()
        }
        send("mode", ["mode": next])
    }
    private func rememberFrontmostApplication() {
        guard let frontmost = NSWorkspace.shared.frontmostApplication,
              frontmost.processIdentifier != ProcessInfo.processInfo.processIdentifier else { return }
        returnApplication = frontmost
    }
    private func restorePreviousApplication() {
        guard let previous = returnApplication else { return }
        returnApplication = nil
        if !previous.isTerminated { previous.activate(options: [.activateIgnoringOtherApps]) }
    }
    private func handle(_ command: [String: Any]) {
        switch command["type"] as? String ?? "" {
        case "state":
            view.insects = command["insects"] as? [[String: Any]] ?? []
            view.offeringPlate = command["placed_item"] as? String == "offering_plate"
        case "timer_expired": statusItem.button?.title = "天姥 ⏰"
        case "timer_dismissed": statusItem.button?.title = "天姥"
        case "mode": setMode(command["mode"] as? String ?? "passthrough")
        case "hide": window.orderOut(nil); send("overlay_visibility", ["visible": false])
        case "show": window.orderFrontRegardless(); send("overlay_visibility", ["visible": true])
        case "quit": NSApp.terminate(nil)
        default: break
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

let app = NSApplication.shared
let host = Host()
app.delegate = host
app.run()
