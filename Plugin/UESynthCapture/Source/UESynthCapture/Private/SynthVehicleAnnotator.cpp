#include "SynthVehicleAnnotator.h"
#include "SynthCaptureSubsystem.h"
#include "Components/SkeletalMeshComponent.h"
#include "Camera/CameraComponent.h"
#include "Engine/World.h"
#include "SceneView.h"
#include "GameFramework/Actor.h"
#include "Engine/HitResult.h"
#include "CollisionQueryParams.h"

namespace
{
    // Returns true and fills OutPixel if WorldP is in front of the camera.
    // Mirrors the NDC math in CapturePoints.
    bool ProjectWorldPointToPixel(
        const FTransform& CamXform, float FieldOfViewDeg,
        int32 ImageWidth, int32 ImageHeight,
        const FVector& WorldP, FVector2D& OutPixel)
    {
        const FVector CamLocalP = CamXform.InverseTransformPosition(WorldP);
        if (CamLocalP.X <= 0.0f)
        {
            return false;
        }
        const float FOVHalfRad = FMath::DegreesToRadians(FieldOfViewDeg * 0.5f);
        const float AspectRatio = static_cast<float>(ImageWidth) / static_cast<float>(ImageHeight);
        const float HalfImgW = ImageWidth * 0.5f;
        const float HalfImgH = ImageHeight * 0.5f;
        const float NDCx = (CamLocalP.Y / CamLocalP.X) / FMath::Tan(FOVHalfRad);
        const float NDCy = (CamLocalP.Z / CamLocalP.X) / FMath::Tan(FOVHalfRad) * AspectRatio;
        OutPixel.X = HalfImgW + NDCx * HalfImgW;
        OutPixel.Y = HalfImgH - NDCy * HalfImgH;
        return true;
    }
}

USynthVehicleAnnotator::USynthVehicleAnnotator()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void USynthVehicleAnnotator::BeginPlay()
{
    Super::BeginPlay();
    if (UWorld* W = GetWorld())
    {
        if (USynthCaptureSubsystem* Sub = W->GetSubsystem<USynthCaptureSubsystem>())
        {
            Sub->RegisterAnnotator(this);
        }
    }
}

void USynthVehicleAnnotator::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (UWorld* W = GetWorld())
    {
        if (USynthCaptureSubsystem* Sub = W->GetSubsystem<USynthCaptureSubsystem>())
        {
            Sub->UnregisterAnnotator(this);
        }
    }
    Super::EndPlay(EndPlayReason);
}

USkeletalMeshComponent* USynthVehicleAnnotator::GetMesh() const
{
    if (AActor* Owner = GetOwner())
    {
        return Owner->FindComponentByClass<USkeletalMeshComponent>();
    }
    return nullptr;
}

TArray<FCapturedKeypoint> USynthVehicleAnnotator::CapturePoints(UCameraComponent* CameraComp, int32 ImageWidth, int32 ImageHeight) const
{
    TArray<FCapturedKeypoint> Out;
    Out.SetNum(24);

    USkeletalMeshComponent* Mesh = GetMesh();
    AActor* Owner = GetOwner();
    if (!Owner || !CameraComp || !GetWorld())
    {
        return Out;
    }

    static const TArray<FString> SchemaOrder = {
        TEXT("Right_Front_wheel"), TEXT("Left_Front_wheel"),
        TEXT("Right_Back_wheel"), TEXT("Left_Back_wheel"),
        TEXT("Right_Front_HeadLight"), TEXT("Left_Front_HeadLight"),
        TEXT("Right_Back_HeadLight"), TEXT("Left_Back_HeadLight"),
        TEXT("Exhaust"),
        TEXT("Right_Front_Top"), TEXT("Left_Front_Top"),
        TEXT("Right_Back_Top"), TEXT("Left_Back_Top"),
        TEXT("Center"),
        TEXT("Left_Side_Mirror"), TEXT("Right_Side_Mirror"),
        TEXT("Front_Left_Bumper_Corner"), TEXT("Front_Right_Bumper_Corner"),
        TEXT("Rear_Left_Bumper_Corner"), TEXT("Rear_Right_Bumper_Corner"),
        TEXT("Windshield_Bottom_Left"), TEXT("Windshield_Bottom_Right"),
        TEXT("Rear_Window_Bottom_Left"), TEXT("Rear_Window_Bottom_Right"),
    };

    const FTransform CamXform = CameraComp->GetComponentTransform();
    const FVector CamLoc = CamXform.GetLocation();
    const float FOVHalfRad = FMath::DegreesToRadians(CameraComp->FieldOfView * 0.5f);
    const float AspectRatio = static_cast<float>(ImageWidth) / static_cast<float>(ImageHeight);
    const float HalfImgW = ImageWidth * 0.5f;
    const float HalfImgH = ImageHeight * 0.5f;

    for (int32 i = 0; i < 24; ++i)
    {
        const FString& SchemaName = SchemaOrder[i];
        FVector WorldP;
        if (const FVector* LocalP = LocalPointBySchemaName.Find(SchemaName))
        {
            // explicit actor-local point (composite static-mesh vehicles)
            WorldP = Owner->GetActorTransform().TransformPosition(*LocalP);
        }
        else
        {
            const FName* SocketName = SocketBySchemaName.Find(SchemaName);
            if (!Mesh || !SocketName || !Mesh->DoesSocketExist(*SocketName))
            {
                // not configured; visibility 0
                continue;
            }
            WorldP = Mesh->GetSocketTransform(*SocketName, RTS_World).GetLocation();
        }

        // Transform to camera local space
        const FVector CamLocalP = CamXform.InverseTransformPosition(WorldP);

        // UE camera looks down +X. Behind camera if X <= 0.
        if (CamLocalP.X <= 0.0f)
        {
            continue;
        }

        // Project to image plane: normalized device coords -> pixels
        const float NDCx = (CamLocalP.Y / CamLocalP.X) / FMath::Tan(FOVHalfRad);
        const float NDCy = (CamLocalP.Z / CamLocalP.X) / FMath::Tan(FOVHalfRad) * AspectRatio;
        const float PixelX = HalfImgW + NDCx * HalfImgW;
        const float PixelY = HalfImgH - NDCy * HalfImgH;

        // Off-screen?
        if (PixelX < 0 || PixelX >= ImageWidth || PixelY < 0 || PixelY >= ImageHeight)
        {
            continue;
        }

        Out[i].ImageX = PixelX;
        Out[i].ImageY = PixelY;

        // Occlusion ray-cast from camera to the point. The vehicle itself is NOT
        // ignored: CarFusion semantics count self-occlusion (far-side wheel behind
        // the body) as v=1. The 40cm tolerance keeps interior anchor points (wheel
        // centers ~34cm inside the tire) "visible" when their surface faces the camera.
        FHitResult Hit;
        FCollisionQueryParams Params(SCENE_QUERY_STAT(SynthKeypointVis), /*bTraceComplex*/ true);
        const bool bBlocked = GetWorld()->LineTraceSingleByChannel(
            Hit, CamLoc, WorldP, ECC_Visibility, Params);

        const float DistToBlocker = bBlocked ? (Hit.ImpactPoint - CamLoc).Size() : TNumericLimits<float>::Max();
        const float DistToPoint = (WorldP - CamLoc).Size();

        bool bVisible = (!bBlocked || DistToBlocker > DistToPoint - VisibilityToleranceCm);

        // Backface guard: one-sided collision lets the forward ray exit an enclosing
        // mesh (e.g. a camera placed inside another car) without a hit. The reverse
        // ray meets that mesh's front faces, so a blocker farther than the tolerance
        // from the point flips the verdict to occluded.
        if (bVisible)
        {
            FHitResult BackHit;
            const bool bBackBlocked = GetWorld()->LineTraceSingleByChannel(
                BackHit, WorldP, CamLoc, ECC_Visibility, Params);
            if (bBackBlocked && (BackHit.ImpactPoint - WorldP).Size() > VisibilityToleranceCm)
            {
                bVisible = false;
            }
        }

        Out[i].Visibility = bVisible ? 2 : 1;
    }

    return Out;
}

FVector4 USynthVehicleAnnotator::CaptureMeshBBox(UCameraComponent* CameraComp, int32 ImageWidth, int32 ImageHeight) const
{
    const FVector4 Degenerate(0.0, 0.0, 0.0, 0.0);
    AActor* Owner = GetOwner();
    if (!Owner || !CameraComp)
    {
        return Degenerate;
    }

    FVector Origin, Extent;
    Owner->GetActorBounds(/*bOnlyCollidingComponents*/ false, Origin, Extent);

    const FTransform CamXform = CameraComp->GetComponentTransform();
    const float FieldOfViewDeg = CameraComp->FieldOfView;

    float MinX = TNumericLimits<float>::Max();
    float MinY = TNumericLimits<float>::Max();
    float MaxX = -TNumericLimits<float>::Max();
    float MaxY = -TNumericLimits<float>::Max();
    int32 Valid = 0;

    for (int32 sx = -1; sx <= 1; sx += 2)
    for (int32 sy = -1; sy <= 1; sy += 2)
    for (int32 sz = -1; sz <= 1; sz += 2)
    {
        const FVector Corner = Origin + FVector(sx * Extent.X, sy * Extent.Y, sz * Extent.Z);
        FVector2D Px;
        if (ProjectWorldPointToPixel(CamXform, FieldOfViewDeg, ImageWidth, ImageHeight, Corner, Px))
        {
            MinX = FMath::Min(MinX, static_cast<float>(Px.X));
            MinY = FMath::Min(MinY, static_cast<float>(Px.Y));
            MaxX = FMath::Max(MaxX, static_cast<float>(Px.X));
            MaxY = FMath::Max(MaxY, static_cast<float>(Px.Y));
            ++Valid;
        }
    }

    if (Valid < 2)
    {
        return Degenerate;
    }

    MinX = FMath::Clamp(MinX, 0.0f, static_cast<float>(ImageWidth));
    MaxX = FMath::Clamp(MaxX, 0.0f, static_cast<float>(ImageWidth));
    MinY = FMath::Clamp(MinY, 0.0f, static_cast<float>(ImageHeight));
    MaxY = FMath::Clamp(MaxY, 0.0f, static_cast<float>(ImageHeight));
    return FVector4(MinX, MinY, MaxX, MaxY);
}
