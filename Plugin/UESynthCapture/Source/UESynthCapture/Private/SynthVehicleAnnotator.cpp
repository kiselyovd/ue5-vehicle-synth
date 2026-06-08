#include "SynthVehicleAnnotator.h"
#include "SynthCaptureSubsystem.h"
#include "Components/SkeletalMeshComponent.h"
#include "Camera/CameraComponent.h"
#include "Engine/World.h"
#include "SceneView.h"
#include "GameFramework/Actor.h"
#include "Engine/HitResult.h"
#include "CollisionQueryParams.h"

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
    if (!Mesh || !CameraComp || !GetWorld())
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
        const FName* SocketName = SocketBySchemaName.Find(SchemaName);
        if (!SocketName || !Mesh->DoesSocketExist(*SocketName))
        {
            // socket not configured; visibility 0
            continue;
        }

        const FTransform SocketWorldXform = Mesh->GetSocketTransform(*SocketName, RTS_World);
        const FVector WorldP = SocketWorldXform.GetLocation();

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

        // Occlusion ray-cast: from camera to world point, see if anything except this vehicle blocks
        FHitResult Hit;
        FCollisionQueryParams Params;
        Params.AddIgnoredActor(GetOwner());
        const bool bBlocked = GetWorld()->LineTraceSingleByChannel(
            Hit, CamLoc, WorldP, ECC_Visibility, Params);

        const float DistToBlocker = bBlocked ? (Hit.ImpactPoint - CamLoc).Size() : TNumericLimits<float>::Max();
        const float DistToPoint = (WorldP - CamLoc).Size();

        if (!bBlocked || DistToBlocker > DistToPoint - 5.0f)
        {
            Out[i].Visibility = 2;  // visible
        }
        else
        {
            Out[i].Visibility = 1;  // labeled but occluded
        }
    }

    return Out;
}
