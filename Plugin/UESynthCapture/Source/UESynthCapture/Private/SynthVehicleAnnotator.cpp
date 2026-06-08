#include "SynthVehicleAnnotator.h"
#include "SynthCaptureSubsystem.h"
#include "Components/SkeletalMeshComponent.h"
#include "Camera/CameraComponent.h"
#include "Engine/World.h"

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
    // Implemented in Task 11.
    TArray<FCapturedKeypoint> Result;
    Result.SetNum(24);
    return Result;
}
